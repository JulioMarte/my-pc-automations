# Testing - local-proxy

Guia de pruebas del proyecto. Todo el suite es **hermetico**: los servidores
escuchan en `127.0.0.1` con puerto `0` (puerto efimero) y no se toca la red
externa ni Tailscale. No hay dependencias de runtime: las pruebas corren con el
runner nativo `node:test`.

---

## Requisitos

- Node 22.18 o superior (el proyecto se desarrolla y valida con Node 24).
- Dependencias de desarrollo instaladas (`npm install`): `typescript` y
  `@types/node`.
- No hace falta build (`dist/`) para probar: `node --test` ejecuta los `.ts`
  directamente con el type-stripping de Node.

---

## Suite completa

```bash
npm test
```

`npm test` es `node --test`, que descubre y ejecuta todos los archivos
`test/*.test.ts` (unit + integracion + journeys). Al final imprime el resumen:

```text
ℹ tests 134
ℹ suites 0
ℹ pass 134
ℹ fail 0
ℹ duration_ms ...
```

Notas:

- Los archivos de test corren en paralelo entre si; por eso cada test usa
  puertos efimeros y no comparte estado global.
- Para ejecutar un solo archivo:
  ```bash
  node --test test/router.test.ts
  ```
- Para filtrar por nombre de test:
  ```bash
  node --test --test-name-pattern="sticky" test/journey.test.ts
  ```

---

## Journeys end-to-end

`test/journey.test.ts` recorre flujos completos de un usuario contra un gateway
real con varios exits, usando sockets reales (nada simulado). Es deterministico:
el orden de seleccion P2C se controla ajustando la carga (`active`) del pool.

```bash
node --test test/journey.test.ts
```

Que cubre cada jornada:

| Jornada | Comportamiento verificado |
|---|---|
| Rotacion | El body del origen llega correcto y `x-exit-name` es un exit sano. |
| Sesion sticky + rotate | `agent-session-abc` repite exit; `agent-rotate-session-abc` lo cambia y re-apunta la sesion. |
| Exit forzado | `agent-exit-vps-02` (nombre con guiones) pega en `vps-02`. |
| Filtro por ubicacion | `agent-loc-us-ny` solo usa ese exit; una ubicacion sin exits devuelve `503`. |
| Failover | Con un exit muerto la peticion sigue funcionando; al caer tambien el sano, el gateway acaba devolviendo `503`. |
| SOCKS5 | Tunel SOCKS5 con DNS remoto (`localhost`) y metering `socks5` en `stats.jsonl`. |
| Auth y limites | Password incorrecta -> `407`; `MAX_CONNECTIONS_PER_USER` alcanzado -> `429`. |
| Observabilidad | `/__stats?token=` lista exits y sesiones activas; `stats.jsonl` tiene lineas de metering. |

---

## Herramienta de estres

`scripts/stress.ts` es un generador de carga **autocontenido** (no importa
`test/helpers.ts`). Levanta en el mismo proceso un origen HTTP, un exit real y un
gateway con **dos exits**: uno sano y otro apuntando a un puerto muerto, para
ejercitar el failover durante toda la corrida. El cliente HTTP minimo va inline.

```bash
node scripts/stress.ts
node scripts/stress.ts --connections=20 --requests=50 --mode=http
node scripts/stress.ts --connections=20 --requests=50 --mode=connect
node scripts/stress.ts --size=8192 --duration=10 --max-error-rate=0.05
```

### Flags

| Flag | Env | Default | Descripcion |
|---|---|---|---|
| `--connections` | `STRESS_CONNECTIONS` | `10` | Workers concurrentes. |
| `--requests` | `STRESS_REQUESTS` | `50` | Peticiones por worker (se ignora si hay `--duration`). |
| `--size` | `STRESS_SIZE` | `1024` | Bytes de payload por peticion. |
| `--mode` | `STRESS_MODE` | `http` | `http` o `connect`. |
| `--max-error-rate` | `STRESS_MAX_ERROR_RATE` | `0.01` | Umbral de error (0.01 = 1%). |
| `--duration` | `STRESS_DURATION` | `0` | Segundos de corrida; si es > 0 ignora `--requests`. |
| `--user` / `--pass` | `STRESS_USER` / `STRESS_PASS` | `stress` / `clave` | Credenciales del gateway. |
| `--timeout` | `STRESS_TIMEOUT_MS` | `10000` | Timeout por peticion en ms. |

Se acepta `--flag=valor` y `--flag valor`.

### Modos

- `--mode=http`: `GET` absoluto a traves del proxy HTTP. El origen devuelve
  `size` bytes y se verifica el largo del body.
- `--mode=connect`: se abre un tunel `CONNECT` crudo y se envia un `POST` con
  `size` bytes; el origen hace eco y se verifica que vuelvan los mismos bytes.

### Como leer la salida

Primero una tabla humana y luego el mismo resumen en JSON:

```text
local-proxy stress
  modo               connect
  workers            20
  peticiones/worker  50
  payload            1.0 KiB
  total              1000
  ok                 1000
  errores            0
  tasa error         0.00% (max 1.00%)
  req/s              166.5
  p50                111.93 ms
  p95                182.07 ms
  p99                204.27 ms
  max                222.04 ms
  bytes up           1.06 MiB
  bytes down         1.11 MiB
  elapsed            6.01 s
  peak RSS           103.36 MiB
  resultado          OK
```

- `total` / `ok` / `errores`: conteos de peticiones.
- `tasa error`: `errores / total`; se compara contra `--max-error-rate`.
- `req/s`: throughput total de la corrida.
- `p50/p95/p99/max`: latencia por peticion en milisegundos.
- `bytes up/down`: bytes leidos/escritos por el cliente (incluyen framing HTTP;
  en `connect` no cuentan el handshake `CONNECT`).
- `peak RSS`: pico de memoria residente del proceso (`process.memoryUsage().rss`).
- `resultado`: `OK` si `tasa error <= maxErrorRate`, `FALLO` en caso contrario.

**Codigo de salida**: `0` si pasa el umbral, `1` si lo supera. Util para CI.

---

## Que cubre cada capa

| Capa | Archivos | Alcance |
|---|---|---|
| Unit | `test/router.test.ts`, `test/limits.test.ts`, `test/metrics.test.ts`, `test/logger.test.ts`, `test/env.test.ts`, `test/upgrade.test.ts` | Funciones puras: parseo de usuarios, P2C, circuit breaker, sesiones, limiter, formato Prometheus, redaccion de logs. |
| Integracion | `test/integration.test.ts`, `test/gateway.test.ts`, `test/exit.test.ts`, `test/reload.test.ts`, `test/ops.test.ts`, `test/monitor.test.ts` | Cada pieza con sockets reales: HTTP/CONNECT/SOCKS5/upgrade, auth, failover, recarga en caliente, draining, health, panel, monitor. |
| E2E journey | `test/journey.test.ts` | Flujos completos de usuario a traves de gateway + varios exits, de punta a punta. |
| Estres | `scripts/stress.ts` | Carga concurrente sostenida, failover bajo carga, throughput, percentiles de latencia y RSS. |

---

## Alcance y advertencias

- **No hay red externa**: no se prueba contra internet, Tailscale real ni exits
  remotos. La SSRF/`blockPrivate` se prueba con literales locales.
- **Latencias del stress**: dependen fuertemente de la maquina; sirven para
  comparar corridas en el mismo equipo, no como benchmark absoluto.
- **El exit muerto es intencional**: el stress mantiene sus umbrales de salud
  altos para que el P2C lo siga eligiendo y el failover se ejerza todo el
  tiempo; por eso el throughput es menor que con un solo exit sano.
- **No cubierto aqui**: HTTPS/TLS de extremo a extremo, WebSocket (tiene test
  propio en `test/integration.test.ts`), IPv6 (opcional segun la maquina),
  servicios de Windows/systemd y despliegue.
