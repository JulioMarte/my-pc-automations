# local-proxy

Proxy residencial **local** estilo proveedor comercial, montado sobre tu red Tailscale.
Expone un único endpoint con **HTTP/HTTPS (CONNECT)** y **SOCKS5**, con autenticación por
usuario/clave y semántica de **sesiones sticky**, **rotación** y **selección de salida**
(igual que usan los proveedores de proxies residenciales), pero el tráfico sale por **tus
máquinas** (casa, VPS, etc.).

---

## Stack: por qué Node puro y no gost/3proxy

Se investigaron las alternativas maduras (docs primarias, sept. 2026) antes de decidir:

| Herramienta | Qué aporta | Por qué no reemplaza el gateway |
|---|---|---|
| [gost v3](https://gost.run) (7.5k★) | Multi-protocolo, cadenas, selector `round/rand/fifo/hash/parallel`, health marking (`maxFails/failTimeout`), plugins HTTP de auth/observer/limiter, WebAPI | El `matcher` de chain groups **solo matchea `Host`**; no hay sticky sessions con TTL ni selección por `exit`/`loc` por username |
| 3proxy / Dante | Proxies maduros, ACLs, rotación de parents | Sin sticky con TTL ni filtrado por ubicación por usuario; Dante es solo SOCKS |
| HAProxy / nginx | Balanceo TCP excelente | No entienden `Proxy-Authorization`; no implementan la semántica de username |
| sing-box / Xray | Routing por usuario, selectores de outbound | Sin sesiones sticky con TTL ni rotación por conexión configurables |

**Conclusión:** la semántica estilo proveedor (sesión sticky, rotación, `exit`, `loc`) es el
producto, y ninguna herramienta la trae de fábrica. El gateway custom está justificado. Se
eligió **Node.js sin dependencias de runtime** por consistencia con el repo, cero binarios y
facilidad de auditar. El código vive en **TypeScript ESM** (`src/`) y se compila a `dist/` con
`tsc` (TypeScript y `@types/node` son solo devDependencies). Si algún día necesitas UDP o más
protocolos en el **exit**, gost es el reemplazo natural de `src/exit.ts`:

```bash
gost -L "http://exituser:exitpass@100.110.109.28:8899"
```

### Runtime: Node.js en producción, Bun para desarrollo

Producción se queda en **Node.js**, no Bun: el gateway depende de túneles HTTP `CONNECT`
(socket crudo) y corre en Windows, y `Bun.serve` no soporta `CONNECT` (necesita la capa de
compatibilidad `node:http`, corregida recién en Bun 1.4.0, con crashes abiertos en Windows,
sin LTS y con problemas recientes de *HTTP smuggling*). Bun sí se soporta como runtime de
**desarrollo/herramientas** (TS nativo, `bun test`, `bun --watch`) y el código es
deliberadamente agnóstico: `bun src/gateway.ts` funciona.

---

## Arquitectura

```
                 Tailscale (WireGuard, privado)
  Cliente          ┌──────────────────────────────┐
  (agente, curl,   │  GATEWAY (siempre encendido) │
   navegador) ───► │  - HTTP  :8888 (CONNECT)     │
                   │  - SOCKS5:1080               │
                   │  - auth, sesiones, rotación  │
                   │  - failover, health, métricas│
                   └──────────────┬───────────────┘
                                  │ HTTP CONNECT (a través de Tailscale)
                 ┌────────────────┼─────────────────┐
                 ▼                ▼                 ▼
          ┌────────────┐   ┌────────────┐   ┌────────────┐
          │ EXIT home  │   │ EXIT vps   │   │ EXIT movil │
          │ :8899      │   │ :8899      │   │ :8899      │
          │ IP casa    │   │ IP VPS     │   │ IP datos   │
          └────────────┘   └────────────┘   └────────────┘
```

- **EXIT**: se ejecuta en cada máquina que aporta salida a internet. Solo acepta tráfico
  desde la red Tailscale (se ata a la IP `100.x` y opcionalmente filtra por `EXIT_ALLOW`).
- **GATEWAY**: se ejecuta en la máquina siempre encendida. Es el "backconnect endpoint":
  los clientes se conectan solo aquí y él elige el exit.
- El DNS se resuelve en el exit (el gateway manda `CONNECT host:puerto`), así **no hay
  DNS leaks**.
- Si un exit falla, el gateway **reintenta con el siguiente sano** (hasta agotar los
  candidatos). El failover también cubre respuestas `407/502/503/504` del exit.

---

## Requisitos

- Node.js **22.18+** en todas las máquinas (recomendado Node 24; sin dependencias de runtime).
  El *type stripping* de Node permite correr `.ts` directo en desarrollo; en producción se
  ejecuta el build de `dist/` (`npm run build`).
- Tailscale instalado y activo en todas las máquinas.
- Puertos permitidos entre las máquinas por la ACL de Tailscale.
- Firewall local: permite Node (o los puertos `8888`, `1080`, `8899`) en la interfaz de
  Tailscale. En Windows, la primera ejecución muestra el aviso de Defender; acéptalo solo
  para redes privadas.

---

## Instalación

```bash
cd local-proxy
cp .env.example .env
cp exits.example.json exits.json
npm install
npm run build
```

`npm install` solo trae devDependencies (`typescript`, `@types/node`); `npm run build`
compila `src/*.ts` a `dist/`.

`.env` (valores reales):

| Variable | Descripción |
|---|---|
| `EXIT_NAME` / `EXIT_HOST` / `EXIT_PORT` | Nombre, IP de Tailscale y puerto del exit en **esa** máquina |
| `EXIT_USER` / `EXIT_PASS` | Credenciales que el exit exige al gateway (recomendado) |
| `EXIT_ALLOW` | Lista de IPs exactas (coma) autorizadas a conectar al exit; vacío = todas (ACL de Tailscale). No soporta CIDR |
| `EXIT_CONNECT_TIMEOUT_MS` | Timeout al conectar al destino desde el exit (15 s) |
| `EXIT_BLOCK_PRIVATE` | Bloquea SSRF a loopback/privadas/link-local/CGNAT/metadata y puerto 25 (`true` por defecto; `false` solo para pruebas locales) |
| `EXIT_IDLE_TIMEOUT_MS` | Cierra túneles CONNECT inactivos (0 = desactivado) |
| `GATEWAY_HOST` | IP de Tailscale de la máquina del gateway (**nunca 0.0.0.0**) |
| `GATEWAY_HTTP_PORT` / `GATEWAY_SOCKS_PORT` | Puertos del gateway (8888 / 1080) |
| `PROXY_USERS` | Usuarios de los clientes: `usuario:clave,otro:clave2` |
| `SESSION_TTL_MS` | Duración de una sesión sticky (10 min por defecto) |
| `CONNECT_TIMEOUT_MS` | Timeout del gateway al conectar al exit (20 s) |
| `HEALTH_INTERVAL_MS` | Frecuencia de health checks (60 s; `0` los desactiva) |
| `HEALTH_TARGETS` | Lista de destinos de health check separada por comas, p. ej. `api.ipify.org:443,www.google.com:443` (tiene prioridad sobre `HEALTH_TARGET`) |
| `HEALTH_TARGET` | Fallback de un solo destino si `HEALTH_TARGETS` está vacío (`api.ipify.org:443`) |
| `HEALTH_TIMEOUT_MS` | Timeout del health check (10 s) |
| `MAX_CONNECTIONS` | Límite de conexiones simultáneas del gateway (0 = sin límite). Al superarlo, Node descarta la conexión |
| `MAX_CONNECTIONS_PER_USER` | Límite de conexiones simultáneas por **usuario base/tenant** (0 = ilimitado). Aplica al nombre base, así que `agent-session-x` y `agent-exit-home` comparten la cuota de `agent`. Al superarlo: HTTP `429` con `Retry-After` y, en SOCKS5, conexión rechazada (REP `0x02`) |
| `STATS_TOKEN` | **Obligatorio** para leer `/__stats` (por `?token=` o `Authorization: Bearer`); si queda vacío, `/__stats` responde 403 |
| `EXITS_FILE` / `STATS_FILE` | Rutas de configuración y métricas (relativas al proyecto o absolutas) |
| `LOG_LEVEL` | Nivel mínimo de log: `debug`, `info`, `warn` o `error` (`info` por defecto) |
| `LOG_FORMAT` | Formato de log: `json` (una línea JSON por evento, por defecto) o `text` (legible para desarrollo) |
| `METRICS_TOKEN` | Protege `GET /metrics` en gateway y exit. Vacío = endpoint abierto en el bind de Tailscale; con valor exige `?token=<valor>` o `Authorization: Bearer <valor>` |

`exits.json` (en el gateway):

```json
[
  { "name": "home", "location": "do-santiago", "host": "100.110.109.28", "port": 8899, "user": "exituser", "pass": "exitpass" },
  { "name": "vps",  "location": "us-east",      "host": "100.112.184.84", "port": 8899, "user": "exituser", "pass": "exitpass" }
]
```

Arranque (desarrollo, corre `.ts` directo con el *type stripping* de Node):

```bash
# en cada máquina que aporta salida:
npm run exit            # o npm run dev:exit (con --watch)

# en la máquina siempre encendida:
npm run gateway         # o npm run dev:gateway (con --watch)
```

Producción (corre el build de `dist/`; ejecuta `npm run build` antes de desplegar):

```bash
npm run start:exit      # node dist/exit.js
npm start               # node dist/gateway.js
```

| Script | Qué hace |
|---|---|
| `npm run build` | Compila `src/*.ts` → `dist/` con `tsc` |
| `npm run typecheck` | `tsc --noEmit` (chequeo de tipos sin generar build) |
| `npm run gateway` / `exit` | Corre `src/gateway.ts` / `src/exit.ts` directo |
| `npm run dev:gateway` / `dev:exit` | Igual, con `node --watch` |
| `npm start` / `start:exit` | Corre el build: `dist/gateway.js` / `dist/exit.js` |
| `npm run bun:gateway` / `bun:exit` | Bun corre los mismos `.ts` (soporte de desarrollo) |
| `npm test` | Tests con el runner nativo (`node --test`) |
| `npm run test:bun` | Tests con `bun test` (opcional) |
| `npm run autostart:install` / `autostart:run` / `autostart:uninstall` | Supervisión en Windows |

### Arranque automático

**Windows — sin admin (arranca al iniciar sesión):**

```powershell
npm run autostart:install      # tarea al iniciar sesión + watchdog cada 2 min
npm run autostart:run          # o ejecuta el supervisor en primer plano
npm run autostart:uninstall    # elimina las tareas y detiene los procesos
```

Esto crea dos tareas:
- `local-proxy-autostart`: al iniciar sesión, corre `scripts/proxy-autostart.ps1`, que
  espera a Tailscale y **lanza `exit` y `gateway` desde `dist/`** (compila con
  `npm run build` si falta la build). Reinicia cada rol con **backoff exponencial con
  jitter** y, además de detectar procesos muertos, hace una **sonda TCP por rol** para
  reiniciar un proceso colgado (vivo pero que ya no acepta conexiones).
- `local-proxy-watchdog`: cada 2 minutos **sonda el servicio real** (`GET /healthz` en el
  gateway y `/__health` en el exit) y reinicia si está poco sano, no solo si falta el
  proceso (`scripts/proxy-watchdog.ps1`).

> El runner y el watchdog **requieren la build**: si no existe `dist/`, el runner la genera
> con `npm run build` antes de arrancar.

**Windows — con admin (arranca al ENCENDER la PC, sin login):** recomendado para que
sobreviva reinicios aunque nadie inicie sesión. Se ejecuta **una vez** como administrador:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-autostart-admin.ps1
```

Registra las mismas tareas pero como **SYSTEM** con trigger **AtStartup**, así arrancan al
bootear Windows (Tailscale es un servicio y también arranca solo). Para desinstalarlas
también necesitas admin (`npm run autostart:uninstall` desde una consola elevada).

Logs en `logs/`: `exit.log`, `gateway.log`, `autostart-YYYYMMDD.log`, `watchdog.log`.

> Honestidad: el reintento nativo de Task Scheduler ("restart on failure") resultó poco
> fiable para procesos largos terminados por el sistema; por eso el mecanismo que
> realmente revive el runner es el **watchdog** (cada 2 min). Mientras el runner está
> caído, los procesos `node` siguen sirviendo (quedan huérfanos), así que el proxy no se
> cae; solo se pierde la supervisión hasta que el watchdog lo recupera.

Para arrancar solo un rol: `npm run autostart:install -- -Roles exit`.

**Linux (VPS sin sudo)** — el repo incluye `scripts/exit-daemon.sh`:

```bash
# copia src/, dist/, package.json, scripts/exit-daemon.sh y crea .env con EXIT_HOST de esa máquina
mkdir -p ~/local-proxy/scripts
scp -r src dist package.json tu-usuario@vps:local-proxy/
scp scripts/exit-daemon.sh vps:local-proxy/scripts/
ssh vps 'chmod +x ~/local-proxy/scripts/exit-daemon.sh'

# arranque + keepalive cada 2 minutos (sin systemd ni root)
ssh vps "( crontab -l 2>/dev/null; echo '@reboot \$HOME/local-proxy/scripts/exit-daemon.sh >> \$HOME/local-proxy/cron.log 2>&1'; echo '*/2 * * * * \$HOME/local-proxy/scripts/exit-daemon.sh >> \$HOME/local-proxy/cron.log 2>&1' ) | crontab -"
```

El daemon **lanza `dist/exit.js`**: si `dist/` no existe en el VPS, corre `npm run build`
allí (o copia `dist/` desde tu máquina). Sonda `GET /__health`, usa `flock` para evitar
carreras entre `@reboot` y el keepalive, y aplica backoff exponencial persistido en
`exit.state`.

Si no hay Node instalado y no tienes sudo, el daemon busca también en
`~/.local/node*/bin/node` (instalación por tarball oficial en el home).

**Despliegue actual** (verificado):

| Máquina | Tailscale | Rol | Exit name | Location | IP de salida |
|---|---|---|---|---|---|
| Julio-Marte (Windows) | 100.110.109.28 | gateway + exit | `home` | `do-santiago` | 186.7.156.18 |
| vmi2741977 (Ubuntu 22.04) | 100.112.184.84 | exit | `vps-01` | `us-ny` | 147.93.185.222 |
| vmi3456423 (Debian 13) | 100.70.33.2 | exit | `vps-02` | `us-mo` | 144.126.139.118 |

Todos los exits llevan `EXIT_ALLOW=100.110.109.28`: solo el gateway puede usarlos
(comprobado: desde otro VPS con credenciales válidas devuelve `407`).

Alternativa con root: unit de systemd con `Restart=always` en lugar de cron.

---

## Uso (estilo proveedor)

El **usuario** codifica las opciones. Formato: `base[-opcion-valor]...`. El valor de una
opción **consume el resto del string**, así que no combines dos opciones con valor en el
mismo usuario; si quieres `rotate` con sesión, ponlo **antes**: `agent-rotate-session-abc`.
El nombre base no puede contener `-`.

| Usuario | Comportamiento |
|---|---|
| `agent` | Rotación: elige un exit sano por conexión |
| `agent-session-abc123` | **Sticky**: mantiene el mismo exit durante `SESSION_TTL_MS` (se renueva con cada uso) |
| `agent-rotate` | Ignora la sesión guardada y fuerza una salida nueva (útil como `agent-rotate-session-abc`) |
| `agent-exit-exit-b` | Fuerza el exit llamado `exit-b` (soporta guiones en el nombre) |
| `agent-loc-do-santiago` | Filtra exits por `location` |

La clave es la del usuario base (`PROXY_USERS`). Ejemplos:

```bash
# HTTP/HTTPS (recomendado para navegadores)
curl -x http://agent:secret123@100.110.109.28:8888 https://api.ipify.org

# Sesión sticky
curl -x http://agent-session-abc:secret123@100.110.109.28:8888 https://api.ipify.org

# SOCKS5 (DNS remoto con socks5h)
curl -x socks5h://agent:secret123@100.110.109.28:1080 https://api.ipify.org

# Forzar un exit concreto
curl -x http://agent-exit-vps:secret123@100.110.109.28:8888 https://api.ipify.org
```

### ¿Qué usuario uso? (ejemplos con el usuario de prueba `test`)

Tu usuario y clave reales están en `local-proxy/.env` (`PROXY_USERS`). Hay un usuario de
prueba llamado `test`.

| Quiero... | Usuario a usar |
|---|---|
| Salir **siempre por casa** (IP residencial) | `test-exit-home` |
| **Rotar** entre casa y los VPS | `test` |
| Mantener la misma salida ~10 min | `test-session-miapp` |
| Salir por un exit concreto | `test-exit-vps-01` / `test-exit-vps-02` |
| Salir por una ubicación | `test-loc-us-ny` / `test-loc-us-mo` / `test-loc-do-santiago` |

Los ejemplos listos para copiar (curl, Python, Node, Playwright, Docker, Git, navegador...)
están en [Ejemplos por herramienta](#ejemplos-listos-para-copiar-por-herramienta). Para
conectar un servicio concreto paso a paso (Coolify, Docker) ver la
[Guía fácil](#guía-fácil-dar-acceso-a-tus-servicios-coolify-docker-apps).

---

## Ejemplos listos para copiar (por herramienta)

En todos los ejemplos sustituye `USUARIO:CLAVE` por los tuyos (el de prueba es `test` y su
clave está en `local-proxy/.env`). El endpoint siempre es el mismo:

| Dato | Valor |
|---|---|
| Servidor | `100.110.109.28` |
| Puerto HTTP/HTTPS | `8888` |
| Puerto SOCKS5 | `1080` |

> Recuerda: solo funciona desde dispositivos conectados a tu tailnet. Fuera de Tailscale
> esa dirección no existe.

### curl

```bash
# HTTPS (usa CONNECT por debajo; lo normal para APIs y webs)
curl -x http://USUARIO:CLAVE@100.110.109.28:8888 https://api.ipify.org

# IP residencial fija (siempre casa)
curl -x http://USUARIO-exit-home:CLAVE@100.110.109.28:8888 https://api.ipify.org

# SOCKS5 con DNS remoto (sin fugas de DNS)
curl -x socks5h://USUARIO:CLAVE@100.110.109.28:1080 https://api.ipify.org

# Guardar el resultado de una API
curl -x http://USUARIO:CLAVE@100.110.109.28:8888 -o datos.json https://api.mi-servicio.com/v1/datos
```

### Python

```python
# requests (respeta HTTP_PROXY/HTTPS_PROXY si no pasas proxies=)
import requests
proxy = "http://USUARIO:CLAVE@100.110.109.28:8888"
print(requests.get("https://api.ipify.org", proxies={"http": proxy, "https": proxy}, timeout=30).text)
```

```python
# httpx
import httpx
proxy = "http://USUARIO:CLAVE@100.110.109.28:8888"
print(httpx.get("https://api.ipify.org", proxy=proxy, timeout=30).text)
```

### Node.js

```js
// Opción A (Node 24+, experimental): por variables de entorno
//   HTTP_PROXY=http://USUARIO:CLAVE@100.110.109.28:8888
//   HTTPS_PROXY=http://USUARIO:CLAVE@100.110.109.28:8888
//   NODE_USE_ENV_PROXY=1
//   node app.js
```

```js
// Opción B: undici (npm i undici)
const { ProxyAgent, fetch } = require('undici');
const dispatcher = new ProxyAgent('http://USUARIO:CLAVE@100.110.109.28:8888');
const response = await fetch('https://api.ipify.org', { dispatcher });
console.log(await response.text());
```

```js
// Opción C: axios (npm i axios)
const axios = require('axios');
const { data } = await axios.get('https://api.ipify.org', {
  proxy: {
    host: '100.110.109.28',
    port: 8888,
    auth: { username: 'USUARIO', password: 'CLAVE' }, // para casa: USUARIO-exit-home
  },
  timeout: 30000,
});
console.log(data);
```

### Playwright / Puppeteer

```js
// Playwright (aplica a todo el navegador)
const { chromium } = require('playwright');
const browser = await chromium.launch({
  proxy: {
    server: 'http://100.110.109.28:8888',
    username: 'USUARIO-exit-home', // residencial fijo
    password: 'CLAVE',
  },
});
```

```js
// Puppeteer
const puppeteer = require('puppeteer');
const browser = await puppeteer.launch({
  args: ['--proxy-server=http://100.110.109.28:8888'],
});
const page = await browser.newPage();
await page.authenticate({ username: 'USUARIO-exit-home', password: 'CLAVE' });
```

### Docker y Docker Compose

```bash
# Un contenedor puntual
docker run --rm \
  -e HTTP_PROXY=http://USUARIO:CLAVE@100.110.109.28:8888 \
  -e HTTPS_PROXY=http://USUARIO:CLAVE@100.110.109.28:8888 \
  -e NO_PROXY=localhost,127.0.0.1 \
  curlimages/curl -sS https://api.ipify.org

# Build de una imagen que necesita internet
docker build \
  --build-arg HTTP_PROXY=http://USUARIO:CLAVE@100.110.109.28:8888 \
  --build-arg HTTPS_PROXY=http://USUARIO:CLAVE@100.110.109.28:8888 \
  -t mi-app .
```

```yaml
# docker-compose.yml
services:
  app:
    image: mi-app
    environment:
      HTTP_PROXY: http://USUARIO:CLAVE@100.110.109.28:8888
      HTTPS_PROXY: http://USUARIO:CLAVE@100.110.109.28:8888
      NO_PROXY: localhost,127.0.0.1,postgres,redis,mysql
```

> En Coolify estas mismas variables van en **Environment Variables** de la app. Ver la
> [Guía fácil](#guía-fácil-dar-acceso-a-tus-servicios-coolify-docker-apps).

### Git, wget y npm

```bash
# Git (solo para ese comando, no cambia tu config global)
git -c http.proxy=http://USUARIO:CLAVE@100.110.109.28:8888 clone https://github.com/algo/repo.git

# wget
wget -e use_proxy=yes -e https_proxy=http://USUARIO:CLAVE@100.110.109.28:8888 https://api.ipify.org

# npm (solo para una instalación)
npm --proxy http://USUARIO:CLAVE@100.110.109.28:8888 --https-proxy http://USUARIO:CLAVE@100.110.109.28:8888 install
```

### PowerShell

```powershell
$proxy = 'http://100.110.109.28:8888'
$cred = New-Object System.Management.Automation.PSCredential(
  'USUARIO-exit-home',
  (ConvertTo-SecureString 'CLAVE' -AsPlainText -Force)
)
Invoke-WebRequest -Uri 'https://api.ipify.org' -Proxy $proxy -ProxyCredential $cred
```

### Postman

Postman **no** usa el proxy en el campo de URL: la URL es el destino y el proxy se configura
aparte. Es el error más común (`407`).

1. Campo de URL: solo el destino, por ejemplo `https://api.ipify.org`.
2. **Settings** (⚙) → **Proxy** → **Add a custom proxy configuration**:
   - Proxy Type `HTTP`, Proxy Server `100.110.109.28`, Proxy Port `8888`
   - **Proxy Auth** ON → Username `test-exit-home`, Password (la de `.env`)
   - **Bypass proxy**: `localhost,127.0.0.1`; desactiva **Use System Proxy**
3. **Send**. Debe devolver tu IP residencial (`186.7.156.18`).

> El proxy de Postman es **global** (aplica a todas sus peticiones), no por request.
> Si pones `http://usuario:clave@100.110.109.28:8888` en la URL, Postman lo manda como
> `Authorization` en vez de `Proxy-Authorization` y el gateway responde `407`.

### Navegador (Firefox / Chrome)

- **Firefox**: Ajustes → Red → Configuración manual → Proxy HTTP `100.110.109.28` puerto
  `8888`, marca "Usar también este proxy para HTTPS". Cuando pida usuario/clave, los
  escribes. Para SOCKS5: Proxy SOCKS `100.110.109.28` puerto `1080`, SOCKS v5 y marca
  "Proxy DNS al usar SOCKS v5".
- **Chrome**: `chrome.exe --proxy-server="http://100.110.109.28:8888"` y autentica cuando
  lo pida. Alternativa: extensión tipo FoxyProxy. Recomendado usar un perfil aparte para
  no enrutar todo tu navegación.

### Apps con su propia configuración de proxy

Si la app tiene su propio campo de proxy (Postman, n8n, clientes de API, etc.), usa esa
opción con `http://USUARIO:CLAVE@100.110.109.28:8888` (o `USUARIO-exit-home` para forzar
casa). Si no respeta variables de entorno ni tiene campo de proxy, hay que tocar el código
o la librería HTTP de la app.

### Comprobar por dónde estás saliendo

```bash
curl -x http://USUARIO:CLAVE@100.110.109.28:8888 https://api.ipify.org
```

- `186.7.156.18` → casa (residencial)
- `147.93.185.222` → vps-01 (us-ny)
- `144.126.139.118` → vps-02 (us-mo)

---

## Guía fácil: dar acceso a tus servicios (Coolify, Docker, apps)

Esta sección es para cuando una app concreta necesita salir por tu IP residencial (por
ejemplo una app de Coolify). No hay que tocar rutas ni VPNs: el servicio simplemente apunta
al proxy, y todo lo demás de la máquina sigue funcionando igual.

### 1. Hay dos tipos de claves (no las confundas)

| Clave | Para qué sirve | Dónde vive |
|---|---|---|
| `EXIT_USER` / `EXIT_PASS` | Comunicación **interna** entre el gateway y tus máquinas de salida. Tus apps nunca la ven. | `.env` de cada máquina |
| `PROXY_USERS` | Usuarios que usan **tus servicios** para conectarse al proxy. | `.env` del gateway |

Piensa en el gateway como un edificio: `PROXY_USERS` son los inquilinos con llave y
`EXIT_PASS` es la llave maestra interna del portero.

### 2. Crear un usuario por servicio

Regla de oro: **un usuario por servicio** (`coolify`, `n8n`, `firefox`...). Así puedes
revocar uno sin afectar a los demás y en `/__stats` ves quién gasta qué.

1. Genera una clave aleatoria (PowerShell):

```powershell
-join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
```

2. Abre `local-proxy/.env` **en el gateway** y agrega el usuario a `PROXY_USERS`
   (no borres los que ya están):

```
PROXY_USERS=julio:CLAVE_ACTUAL,coolify:CLAVE_NUEVA,n8n:OTRA_CLAVE
```

   - El nombre **no puede llevar guiones** (`coolify` sí, `mi-coolify` no).
   - La clave **no puede llevar comas**; mejor solo letras y números.

3. Reinicia el gateway (el supervisor lo revive solo en ~15 segundos):

```powershell
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Where-Object { $_.CommandLine -match 'gateway' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Si arrancas el gateway a mano (`npm run gateway`), simplemente vuelve a lanzarlo después de
editar `.env`.

### 3. Darle los datos al servicio

Al servicio le pasas 4 datos: servidor `100.110.109.28`, puerto `8888` (HTTP) o `1080`
(SOCKS5), usuario y clave. En Coolify → tu app → **Environment Variables**:

```
HTTP_PROXY=http://coolify-exit-home:CLAVE_NUEVA@100.110.109.28:8888
HTTPS_PROXY=http://coolify-exit-home:CLAVE_NUEVA@100.110.109.28:8888
NO_PROXY=localhost,127.0.0.1,postgres,mysql,redis
```

- `-exit-home` = **siempre sale por tu casa** (IP residencial). Si usas solo `coolify`,
  rota entre casa y los VPS (IPs de datacenter).
- `NO_PROXY` evita que la app use el proxy para hablar con sus bases de datos internas
  (`postgres`, `redis`, etc.); sin eso se rompe.
- Si el build de la imagen también necesita internet, agrega las mismas variables como
  **Build Variables**.
- Para Python: `requests` respeta las variables de entorno automáticamente.

### 4. Por qué solo funciona dentro de Tailscale

- El proxy **solo escucha en `100.110.109.28`** (dirección privada de Tailscale), no en la
  IP pública. Desde internet normal esa dirección no existe; es como una extensión interna.
- Cualquier máquina de tu tailnet puede usarlo (el laptop, vps-01, vps-02, el celular).
  Los contenedores Docker de esas máquinas también: ya verificado con un contenedor
  `curlimages/curl` en vps-01 saliendo por `186.7.156.18`.
- Para sumar una máquina nueva: instala Tailscale, inicia sesión con tu cuenta y listo.
- Además de Tailscale, el proxy sigue pidiendo usuario y clave.

### 5. Probar que quedó bien

Desde el laptop o cualquier máquina del tailnet:

```powershell
curl.exe -x http://coolify:CLAVE_NUEVA@100.110.109.28:8888 https://api.ipify.org
```

| Resultado | Significa |
|---|---|
| `186.7.156.18` | Funciona y sale por tu casa |
| `407` | Usuario o clave mal escritos |
| `connection refused` | El gateway no está corriendo o no estás en Tailscale |

### 6. Si la app no respeta las variables de entorno

Muchas apps (curl, Python `requests`, Go) usan `HTTP_PROXY`/`HTTPS_PROXY` solas. Otras no:

- **Node.js** con `fetch`/undici **no** las respeta por defecto; en Node 24+ puedes probar
  `NODE_USE_ENV_PROXY=1`, o configurar el proxy en el código (`ProxyAgent`).
- Si la app tiene su propia configuración de proxy, usa la opción de la app con
  `http://usuario-clave@100.110.109.28:8888` (o `usuario-exit-home` para forzar casa).

---

## Salud, failover y recarga en caliente

- Cada `HEALTH_INTERVAL_MS` el gateway abre un `CONNECT` de prueba por cada exit, contra
  los destinos de `HEALTH_TARGETS` (o `HEALTH_TARGET` si aquella está vacía), con **jitter**
  e **histéresis**: 2 fallos consecutivos marcan el exit como no sano y 2 éxitos lo
  recuperan.
- Cada exit tiene un **circuit breaker**: se abre tras 3 fallos consecutivos, pasa a
  *half-open* tras un backoff con jitter y se cierra en el primer éxito.
- Si el exit elegido falla (conexión, timeout o `407/502/503/504` **generado por el exit**),
  el gateway prueba el siguiente candidato. En HTTP plano solo reintenta métodos sin cuerpo
  (`GET`/`HEAD`) para no reenviar bodies; CONNECT y SOCKS5 siempre reintentan.
- Para distinguir un error del exit de un `502/503` legítimo del **origen**, el exit agrega
  el header `x-exit-name` a las respuestas que reenvía. Si usas otro software como exit
  (p. ej. gost), esa marca no existe y un `502/503/504` del origen puede reintentarse en
  otro exit; es inofensivo pero puede marcar un exit como no sano temporalmente.
- Las sesiones están acotadas (máximo 10000) y se limpian por TTL.
- Códigos de estado: `503` + `Retry-After` cuando no hay exits usables; `504` si el exit
  agota el tiempo; `502` para otros fallos de upstream; `429` si un cliente queda bloqueado
  temporalmente por demasiados fallos de autenticación **o** si supera su
  `MAX_CONNECTIONS_PER_USER` (en SOCKS5 el límite por usuario rechaza con REP `0x02`).
- Al guardar `exits.json` el gateway lo recarga solo (hot reload, también en Windows) sin
  perder salud, contadores ni sesiones de exits que siguen existiendo.

---

## Monitoreo

Endpoints del gateway (en el puerto HTTP del proxy, acceso directo, no a través del proxy):

| Endpoint | Auth | Devuelve |
|---|---|---|
| `GET /healthz` | ninguna | Liveness: `200` siempre que el proceso esté vivo |
| `GET /readyz` | ninguna | Readiness: `200` si hay ≥1 exit usable, `503` si no |
| `GET /__stats` | `?token=<STATS_TOKEN>` o `Authorization: Bearer <STATS_TOKEN>` | Exits, salud, conexiones, bytes y sesiones activas |
| `GET /metrics` | ninguna si `METRICS_TOKEN` está vacío; si no, `?token=<METRICS_TOKEN>` o `Authorization: Bearer <METRICS_TOKEN>` | Métricas en formato Prometheus (`text/plain; version=0.0.4`), antes de la auth y solo por ruta relativa |

- `/__stats` **exige `STATS_TOKEN`**: si la variable está vacía, responde `403`
  (estadísticas deshabilitadas). Ya no acepta la auth normal de proxy.
- El exit expone `GET /__health` (sin auth) → `{ok,name,uptimeMs}`.
- El exit también expone `GET /metrics` en su puerto (mismo formato, antes de la auth y
  solo por ruta relativa), protegido por `METRICS_TOKEN` igual que en el gateway.
- `stats.jsonl` → una línea por conexión cerrada (exit, duración, bytes). El metering de
  SOCKS5 cuenta subida y bajada por separado.

### Métricas y logs

**Scraping con Prometheus** (el gateway y cada exit exponen `/metrics` en el puerto del
proxy; los binds son solo Tailscale, así que el scrape ocurre dentro del tailnet):

```yaml
scrape_configs:
  - job_name: local-proxy-gateway
    static_configs: [{ targets: ['100.110.109.28:8888'] }]
  - job_name: local-proxy-exits
    static_configs: [{ targets: ['100.112.184.84:8899', '100.70.33.2:8899'] }]
```

Comprobación rápida (texto plano, formato Prometheus):

```bash
curl http://100.110.109.28:8888/metrics
```

Si defines `METRICS_TOKEN`, añade `?token=<METRICS_TOKEN>` (o la cabecera
`Authorization: Bearer <METRICS_TOKEN>`) a la URL de scrape y al `curl`.

**Métricas del gateway** (todas con prefijo `localproxy_`):

| Métrica | Etiquetas | Descripción |
|---|---|---|
| `requests_total` | `protocol` (`http`/`connect`/`socks5`), `code` (HTTP status o `ok`/`error` en SOCKS) | Peticiones atendidas |
| `bytes_total` | `direction` (`up`/`down`), `exit` | Bytes transferidos |
| `active_connections` | `protocol` | Conexiones activas |
| `user_connections` | `user` (usuario base) | Conexiones activas por usuario base (gauge) |
| `user_limit_rejections_total` | `user` (usuario base) | Conexiones rechazadas por superar `MAX_CONNECTIONS_PER_USER` |
| `global_limit_drops_total` | - | Conexiones descartadas por superar `MAX_CONNECTIONS` (global) |
| `auth_failures_total` / `auth_blocked_total` | - | Fallos de auth y clientes bloqueados temporalmente |
| `upstream_errors_total` | `kind` (`no_exits` o el status numérico) | Errores al conectar al exit |
| `exit_healthy` | `exit` | Salud del exit (1/0) |
| `exit_circuit` | `exit` | Estado del circuit breaker (0=closed, 1=halfOpen, 2=open) |
| `sessions` | - | Sesiones sticky activas |
| `healthcheck_failures_total` | `exit` | Fallos de health check |
| `request_duration_seconds` | `protocol` | Histograma de duración de peticiones |
| `connect_duration_seconds` | `exit` | Histograma de duración del CONNECT al exit |
| `uptime_seconds` | - | Tiempo encendido |
| `build_info` | `version`, `role` | Información de la build |

**Métricas del exit** (prefijo `localproxy_`): `requests_total{code}`,
`bytes_total{direction}`, `active_connections`, `blocked_total{reason}`
(`reason="ssrf"` para bloqueos SSRF), `uptime_seconds` y `build_info{version,role}`.

Las etiquetas son deliberadamente acotadas (no hay etiquetas por host) para controlar la
cardinalidad. La etiqueta `user` se acota a los usuarios base de `PROXY_USERS` (las
variantes `-session-...`, `-exit-...`, etc. no crean series nuevas).

**Logs**: por defecto cada evento es un objeto JSON en una línea con `ts`, `level`, `msg` y
campos de contexto (`role`, `name`, `exit`, etc.). Los secretos (`authorization`,
`proxy-authorization`, `password`, `token`, `cookie`, `secret`) se redactan como
`[redacted]`. `LOG_FORMAT=text` produce una línea legible para desarrollo. Los niveles
`warn` y `error` van a stderr. Ajusta la verbosidad con `LOG_LEVEL`.

---

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `407 Proxy Authentication Required` | Usuario o clave mal escritos | Revisa `PROXY_USERS` en `.env` y reinicia el gateway. El usuario base no lleva `-exit-...` |
| `429 Too Many Requests` | Demasiados fallos de auth seguidos desde ese cliente, **o** alcanzaste tu límite de conexiones concurrentes por usuario (`MAX_CONNECTIONS_PER_USER`) | Si es auth: espera (viene con `Retry-After`) y corrige las credenciales. Si es el límite por usuario: cierra conexiones o súbelo en `.env` (`MAX_CONNECTIONS_PER_USER`; `0` = ilimitado) y reinicia el gateway |
| `502 Bad Gateway` | No hay exits sanos o el destino no responde | Mira `/__stats`; revisa que Tailscale esté arriba en el exit |
| `503 Service Unavailable` | No hay ningún exit usable | Consulta `GET /readyz`; revisa salud y `exits.json` |
| `403 Forbidden` en un destino | El nuevo bloqueo SSRF rechaza loopback/privadas/link-local/CGNAT/metadata o el puerto 25 | Es esperado; para pruebas locales pon `EXIT_BLOCK_PRIVATE=false` |
| `403` al pedir `/__stats` | `STATS_TOKEN` vacío (stats deshabilitadas) o token incorrecto | Define `STATS_TOKEN` en `.env` y reinicia el gateway; usa `?token=...` o `Authorization: Bearer` |
| Los servicios no arrancan tras la migración | Falta la build de `dist/` | Ejecuta `npm run build` y reinicia el servicio |
| `connection refused` | El gateway no corre, o no estás en Tailscale | Comprueba que el puerto 8888 escuche y que la tarea `local-proxy-autostart` esté `Running` |
| La app sigue saliendo con su IP | La app no respeta `HTTP_PROXY` | Configura el proxy dentro de la app (ver los ejemplos por herramienta) |
| Timeout usando `-exit-home` | El laptop está dormido o apagado | Despiértalo, o usa rotación (`USUARIO` sin `-exit-home`) para caer a los VPS |
| El navegador no carga | Host/puerto mal o falta autenticar | Revisa `100.110.109.28:8888` y que pida usuario/clave |

Comprobaciones rápidas:

```powershell
# ¿El gateway está escuchando? (en la máquina del gateway)
netstat -ano | findstr LISTENING | findstr ":8888"

# ¿La tarea de arranque está viva?
Get-ScheduledTask -TaskName 'local-proxy-autostart' | Select-Object TaskName, State

# ¿El servicio responde? (liveness y readiness del gateway)
curl.exe http://100.110.109.28:8888/healthz
curl.exe http://100.110.109.28:8888/readyz

# ¿Qué está pasando? (logs del supervisor y de cada rol)
Get-Content logs\autostart-*.log -Tail 20
```

---

## Tests

```bash
npm test          # runner nativo de Node (node --test) sobre los tests .ts
npm run test:bun  # opcional, con bun test
```

Los tests usan el runner nativo de Node (`node:test`, cero dependencias): parser de usuarios,
auth, rotación, sticky con TTL, `exit`/`loc`/`rotate`, failover (HTTP, CONNECT y SOCKS5),
health checks, allowlist, recarga, y tests de integración reales por socket (HTTP, HEAD,
body grande, CONNECT, SOCKS5 con DNS remoto, WebSocket/Upgrade, IPv6, stats y 407).

---

## Seguridad

1. `GATEWAY_HOST` y `EXIT_HOST` deben ser la **IP de Tailscale** (`100.x`), nunca `0.0.0.0`.
2. Usa credenciales distintas para `PROXY_USERS` y `EXIT_USER/PASS`, largas y aleatorias.
3. Define `EXIT_ALLOW` con la IP del gateway para que el exit rechace cualquier otro peer.
4. En la ACL de Tailscale, limita los puertos `8888`, `1080` y `8899` solo a los
   dispositivos/usuarios que los necesitan.
5. **Nunca** expongas esto con `tailscale funnel` ni abras puertos en el router.
6. `exits.json`, `.env` y `stats.jsonl` están en `.gitignore`: no se suben a git.
7. Las claves se comparan en tiempo constante (`crypto.timingSafeEqual`).
8. El tráfico viaja cifrado por WireGuard dentro del tailnet; el gateway no inspecciona
   contenido, solo enruta.
9. El exit bloquea por defecto peticiones SSRF a loopback (`127/8`, `::1`), rangos privados
   (`10/8`, `172.16/12`, `192.168/16`), CGNAT/tailnet (`100.64/10`), link-local y metadata
   de nube (`169.254/16`), multicast/reservados, IPv6 `fe80::/10` y `fc00::/7`, y el puerto
   25. `EXIT_BLOCK_PRIVATE=false` desactiva el bloqueo (solo para pruebas locales).

---

## Limitaciones honestas

- Una sola IP residencial por ubicación (no hay miles de IPs como un proveedor real).
- Si tu IP es bloqueada por un sitio, no hay rotación infinita que lo arregle.
- Si la máquina del gateway o de los exits se apaga/duerme, el proxy deja de funcionar.
- No soporta UDP (`SOCKS5 ASSOCIATE`/QUIC se degrada a TCP en la mayoría de clientes).
- No habla HTTP/2 hacia los clientes; usa HTTP/1.1 (es lo que usan curl, navegadores y
  agentes al configurar un proxy).
- El nombre base de usuario no puede contener `-`, y `PROXY_USERS` separa usuarios por `,`
  y usuario/clave por `:`, así que la clave no puede contener `,`.
- El reenvío de HTTP plano metrifica el cuerpo (`bytesUp` no cuenta cabeceras); CONNECT y
  SOCKS5 cuentan todo el stream.
- `stats.jsonl` crece sin límite: rótalo tú (logrotate / borrado periódico).
- Al apagar con Ctrl+C puede perderse la última línea de stats de una conexión recién
  cerrada (el archivo se escribe de forma asíncrona).
- Las sesiones y los contadores viven en memoria: reiniciar el gateway pierde las sesiones
  sticky (los clientes obtienen una nueva salida) y reinicia las estadísticas acumuladas;
  `stats.jsonl` sí sobrevive.
- El arranque **sin admin** es al **iniciar sesión**; para que arranque al **encender la PC
  sin que nadie entre** hay que instalar las tareas como SYSTEM una vez con admin (ver
  Arranque automático).
- El health check genera tráfico periódico hacia `HEALTH_TARGETS`/`HEALTH_TARGET` desde cada
  exit (`api.ipify.org` por defecto). Si te importa esa fuga, apúntalos a un host tuyo o pon
  `HEALTH_INTERVAL_MS=0`.
- `/__stats` muestra las sesiones de **todos** los usuarios a quien tenga el `STATS_TOKEN`;
  es un diseño de un solo dueño, no multi-tenant.
- No hay facturación, cuotas ni KYC; es tu red, tu responsabilidad.
- El login de Tailscale de cada máquina debe estar activo y sin expiración de clave.

---

## Rama de trabajo

La migración a TypeScript ESM y el hardening viven en la rama
`feat/local-proxy-ts-hardening`; **`main` está intacta**. Para desplegar esta rama hay que
**recompilar (`npm run build`) y reiniciar el servicio** (el runner/watchdog y el daemon
lanzan desde `dist/`, no desde `src/`).

---

## Roadmap sugerido

- Cuotas por usuario/día (el límite global de conexiones concurrentes ya existe vía
  `MAX_CONNECTIONS`).
- Watchdog que reviva el supervisor de Windows si muere (auto-reparable).
- Panel web mínimo para ver `/__stats` desde el móvil.
- Exit opcional con gost para UDP/QUIC y más protocolos.
- Soporte de `PROXY protocol` y de exits SOCKS5 (no solo HTTP).
