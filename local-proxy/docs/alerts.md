# Alertas ligeras (monitor)

`local-proxy` ya expone un dashboard pull en `GET /panel`. Este monitor es la
opcion push: un script autonomo (`scripts/monitor.ts`) que sondea
`GET /healthz` y `GET /readyz` del gateway y avisa por ntfy, Telegram o un
webhook generico cuando el estado cambia.

- `up`: `healthz` responde `200` **y** `readyz` responde `200`.
- `down`: cualquier otro caso (status distinto de `200`, sin respuesta, timeout).

Solo se notifican **transiciones**:

- `up -> down`: `proxy CAIDO`
- `down -> up`: `proxy RECUPERADO`

No hay dependencias nuevas: usa `fetch` nativo de Node (>= 22.18). No requiere
build; se ejecuta directo desde `scripts/`.

## Como complementa a `/panel`

| | `/panel` | `monitor.ts` |
| --- | --- | --- |
| Modelo | pull (abres el navegador) | push (te avisa el) |
| Requiere tailnet | si | no (solo alcanzar el gateway) |
| Sirve para | diagnostico, detalle | enterarte de caidas/recuperaciones |
| Persistencia | ninguna | `monitor-state.json` (transiciones y cooldown) |

Son complementarios: el monitor avisa, el panel te da el detalle cuando entras.

## Configuracion

Variables de entorno:

| Variable | Default | Descripcion |
| --- | --- | --- |
| `MONITOR_URL` | `http://127.0.0.1:8888` | Base del gateway. Se sondean `/healthz` y `/readyz`. |
| `MONITOR_INTERVAL_MS` | `60000` | Intervalo del bucle (solo sin `--once`). |
| `MONITOR_TIMEOUT_MS` | `5000` | Timeout por peticion de salud. |
| `MONITOR_TOKEN` | (vacio) | Opcional. Si se define, se envia como `Authorization: Bearer` en las sondas. |
| `MONITOR_STATE_FILE` | `monitor-state.json` | Ruta del estado (usar ruta absoluta en tareas programadas). |
| `ALERT_COOLDOWN_MS` | `600000` | Minimo entre alertas. `0` desactiva el cooldown. |
| `ALERT_NTFY_URL` | (vacio) | URL del topic ntfy, p. ej. `https://ntfy.sh/mi-topic`. |
| `ALERT_NTFY_TOKEN` | (vacio) | Opcional. Token de ntfy (se envia como `Authorization: Bearer`). |
| `ALERT_TELEGRAM_BOT_TOKEN` | (vacio) | Token del bot de Telegram. |
| `ALERT_TELEGRAM_CHAT_ID` | (vacio) | Chat destino. Requiere tambien el token. |
| `ALERT_TELEGRAM_API_BASE` | `https://api.telegram.org` | Opcional. Solo para Bot API self-hosted o pruebas. |
| `ALERT_WEBHOOK_URL` | (vacio) | URL que recibe un `POST` JSON. |

> Si el gateway escucha en su IP de Tailscale (`GATEWAY_HOST=100.x`), apunta
> `MONITOR_URL` a esa IP (p. ej. `http://100.110.109.28:8888`), no a
> `127.0.0.1`: en `127.0.0.1:8888` no habra nada escuchando. El monitor tambien
> lee `.env` del proyecto al arrancar, asi que puedes definir ahi `MONITOR_URL`,
> `ALERT_*`, etc.

Reglas:

- Se envia a **todos** los backends configurados. Si no hay ninguno, se registra
  un `warn` y el monitor sigue funcionando (no falla).
- Si un backend falla, los demas igual reciben la alerta; el fallo queda en el
  log.
- Nunca se registran tokens ni URLs con credenciales (el logger redacta campos
  sensibles).

## Ejemplos de backends

### ntfy

```bash
ALERT_NTFY_URL=https://ntfy.sh/mi-topic-secreto
# opcional, si el topic requiere auth:
# ALERT_NTFY_TOKEN=tk_...
node scripts/monitor.ts --once
```

Envia un `POST` con el texto de la alerta como cuerpo.

### Telegram

```bash
ALERT_TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
ALERT_TELEGRAM_CHAT_ID=123456789
node scripts/monitor.ts --once
```

Envia `POST https://api.telegram.org/bot<token>/sendMessage` con
`{ "chat_id": "...", "text": "..." }`.

### Webhook generico

```bash
ALERT_WEBHOOK_URL=https://mi-servicio.example/alerts
node scripts/monitor.ts --once
```

Envia `POST` con `content-type: application/json` y cuerpo:

```json
{
  "source": "local-proxy-monitor",
  "prev": "up",
  "next": "down",
  "detail": "healthz=200 readyz=503",
  "text": "proxy CAIDO: healthz=200 readyz=503"
}
```

## Como ejecutarlo

### Bucle continuo

```bash
node scripts/monitor.ts
```

Sondea cada `MONITOR_INTERVAL_MS` y sale limpio con `Ctrl+C` (`SIGINT`/`SIGTERM`).

### Modo `--once`

```bash
node scripts/monitor.ts --once
```

Hace **una sola pasada** y termina. El estado (`up`/`down` y el instante de la
ultima alerta) se guarda en `MONITOR_STATE_FILE`, de modo que dos invocaciones
separadas detectan la transicion igual que el bucle. Es el modo recomendado para
tareas programadas (Task Scheduler, cron, systemd timer), porque no deja un
proceso vivo y el cooldown sobrevive entre ejecuciones.

### Windows: Task Scheduler cada 5 minutos

Crea un `.cmd` que fije las variables y llame a `node` (Task Scheduler no hereda
tu entorno de la shell):

```bat
@echo off
set "MONITOR_URL=http://127.0.0.1:8888"
set "MONITOR_STATE_FILE=C:\local-proxy\monitor-state.json"
set "ALERT_NTFY_URL=https://ntfy.sh/mi-topic-secreto"
"C:\Program Files\nodejs\node.exe" "C:\local-proxy\scripts\monitor.ts" --once
```

Registra la tarea (cada 5 minutos):

```powershell
schtasks /Create /TN "local-proxy-monitor" /SC MINUTE /MO 5 ^
  /TR "C:\local-proxy\monitor-once.cmd" /F
```

Verificacion manual:

```powershell
schtasks /Run /TN "local-proxy-monitor"
```

### Linux: cron cada 5 minutos

```cron
*/5 * * * * cd /home/usuario/local-proxy && /usr/bin/node scripts/monitor.ts --once >> /home/usuario/local-proxy/logs/monitor.log 2>&1
```

Cron no carga tu entorno: define las variables en el crontab, en un wrapper, o
usa `EnvironmentFile` con systemd.

### Linux: systemd timer

`/etc/systemd/system/local-proxy-monitor.service`:

```ini
[Unit]
Description=local-proxy health monitor (one shot)

[Service]
Type=oneshot
WorkingDirectory=/home/usuario/local-proxy
EnvironmentFile=/home/usuario/local-proxy/monitor.env
ExecStart=/usr/bin/node scripts/monitor.ts --once
```

`/etc/systemd/system/local-proxy-monitor.timer`:

```ini
[Unit]
Description=Ejecuta el monitor de local-proxy cada 5 minutos

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

Activa el timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now local-proxy-monitor.timer
systemctl list-timers local-proxy-monitor.timer
```

En `monitor.env` pon una variable por linea (`CLAVE=valor`).

## Estado, dedupe y cooldown

- `MONITOR_STATE_FILE` guarda `{ "state": "up|down", "lastAlertAt": <epoch ms> }`.
- Solo se alerta en una transicion; si el estado no cambia, no hay alerta.
- `ALERT_COOLDOWN_MS` suprime cualquier alerta si la ultima se envio hace menos
  de ese tiempo (evita tormentas por flapping). La transicion igual se registra
  para no repetirla.
- Si **todos** los envios de una alerta fallan, la transicion no se persiste para
  reintentar en el siguiente ciclo. Si al menos un backend la recibio, se
  persiste (no se reenvia).

Anade `monitor-state.json` a tu `.gitignore` si lo dejas en el repo.

## Scripts sugeridos para `package.json`

```json
"monitor": "node scripts/monitor.ts",
"monitor:once": "node scripts/monitor.ts --once"
```
