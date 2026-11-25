# Corte de produccion vps-01 -> vps-02

Procedimiento para mover la produccion (Coolify y todo lo que gestiona) de vps-01
(`vmi2741977`) a vps-02 (`vmi3456423`, 144.126.139.118 / 2605:a140:2345:6423::1).
Probado como DR de prueba el 2026-11-23 (snapshot `8a286f87`): todo restaura y la
validacion final pasa. Lo que sigue es el corte real, con ventana de parada.

Ayudante en vps-02: `examples/vps02-cutover.sh` (instalado en `/root/cutover/`).

## Estado de partida (2026-11-23)

- vps-02: restaurado desde vps-01, salida a internet de los contenedores bloqueada
  (`dr-egress-block`), trafico hacia vps-01 bloqueado, backups propios activos en el
  repositorio `vps-backups/vmi3456423` (identidad `vmi3456423`, no toca el de vps-01).
- vps-01: sigue en produccion con backups en `vps-backups/vmi2741977`.

## Ensayo general (2026-11-24)

Ayudante completo (`dr` + redeploy de las apps de git con ventana de build + `finish`)
con el snapshot `9927e5ad` de vps-01:

- DR: 18 min. Primer intento fallido por una carrera de Coolify (borro la red de
  Firefly en pleno arranque); corregido con reintento (`_coolify_start_until_ready`).
- `postgres-sql` recreado solo (6 bases). Apps de git: redeploy en unos 10 min.
- `finish`: el primer backup fallo por volumenes anonimos nuevos; `finish` ya completa
  la politica. Backup `dfab22e8`, `check` OK, `dr-plan` y `doctor` sin fallos ni avisos.
- Datos comprobados: Vaultwarden (10 usuarios, 732 elementos, quick_check ok),
  Firefly (118 transacciones), n8n (70 workflows).

Segundo ensayo, con el snapshot `72c57274` (el primero de vps-01 con hooks):

- DR: 22 min. El reintento de arranque actuo en real (`mysql-gb7p1...` en "created",
  levanto al segundo intento).
- Imagenes fijadas al digest del origen: 23 (las 2 restantes no tienen digest de
  registro; se construyen en el propio host).
- `40-embedded-db-restore`: 6 bases embebidas restauradas desde sus copias
  consistentes (Vaultwarden, Mailu x2, the-vocal-room, coolify-sentinel, Portainer),
  `quick_check` ok.
- `finish`: politica completada (7 volumenes) y primer backup correcto a la primera.
- Datos: Vaultwarden 10 usuarios / 732 elementos, Firefly 118 transacciones, n8n 70
  workflows.

Duracion estimada de la ventana real: unos 45 min hasta servir desde vps-02, mas la
propagacion de DNS.

## Antes del dia del corte

1. Hecho el 2026-11-24 (snapshot `72c57274`). En vps-01: instalar los hooks del repo
   `hooks/pre-backup.d/40-embedded-db-snapshots`, `hooks/pre-backup.d/45-image-digests`
   y `hooks/restore.d/40-embedded-db-restore` (root:root 0700), corregir
   `excludes.txt` (`/etc/vps-backup/credentials*`) y borrar
   `/etc/vps-backup/credentials.bak-*`. Lanzar `vps-backup backup` y comprobar que el
   snapshot trae `staging/workloads/embedded-db/manifest.tsv` e
   `staging/workloads/images/image-digests.tsv`.
2. Bajar el TTL de los registros DNS a 300 s al menos 24 h antes.
3. Tener a mano el acceso al proveedor DNS y al panel/CLI de Contabo (PTR).

## Ventana de corte

1. **Congelar el trafico en vps-01 sin tocar el estado de Coolify.** No parar apps ni
   servicios desde Coolify: el inventario del backup final los registraria como
   parados y el DR (que reproduce el estado de origen) no los arrancaria. En su lugar:
   - `docker stop coolify-proxy` (corta todo el trafico web hacia las apps);
   - rechazar el correo entrante en los puertos que publica Mailu (Docker se salta ufw):
     `sudo iptables -I DOCKER-USER -p tcp -m multiport --dports 25,465,587,110,143,993,995 -j REJECT`.
     Los servidores remotos reintentan; el correo llega a vps-02 tras el DNS.
   Lo que escriben las tareas internas (p. ej. ejecuciones programadas de n8n) entre el
   backup final y el corte se pierde; es una ventana de minutos.
2. **Backup final en vps-01:** `sudo vps-backup backup` y anotar el ID del snapshot de
   sistema. `sudo vps-backup check`.
3. **Parar vps-01 del todo:** `docker stop` de los contenedores de Coolify
   (`coolify`, `coolify-proxy`, ...) y del resto, para que ningun Coolify vuelva a
   arrancar recursos alli. Desactivar sus timers de vps-backup solo cuando vps-02 ya
   haga backups (paso 7).
4. **DR en vps-02:** `/root/cutover/vps02-cutover.sh dr <snapshot>` y esperar
   `EXIT=0` en `/root/dr-cutover.log` (unos 25 min). Con la salida aun bloqueada, las
   apps que se construyen desde git (`www.quisqueyatech.com`,
   `the-vocal-room-academy`) fallan y la validacion acaba en `EXIT=1` solo por ellas:
   se redespliegan tras el paso 5 (`coolify deploy uuid <uuid>`).
   `postgres-sql-postgres-1` (compose fuera de Coolify) lo recrea el propio ayudante
   al terminar el DR (`PGSQL_EXIT=0` en el log); a mano:
   `/root/cutover/vps02-cutover.sh postgres-sql`.
5. **Abrir salida:** `/root/cutover/vps02-cutover.sh go-live`.
6. **DNS:** apuntar a vps-02 (A 144.126.139.118, AAAA 2605:a140:2345:6423::1) cada
   dominio que sirve Coolify. La lista sale de su base de datos (no se versiona aqui:
   el repositorio es publico):
   `docker exec -i coolify-db psql -At -U coolify -d coolify -c "select fqdn from applications where deleted_at is null union all select fqdn from service_applications where deleted_at is null" | tr , '\n' | sed -E 's#^https?://##; s#[:/].*##' | sort -u`
   Correo: SPF con `ip4:144.126.139.118` (y `ip6:` si se usa) en lugar de la IP de
   vps-01; PTR de 144.126.139.118 -> `mail.quisqueyatech.com` en Contabo. DKIM no
   cambia (la clave viene en el volumen `mailu_mailu_dkim`).
7. **Backups de vps-02:** `/root/cutover/vps02-cutover.sh finish` (identidad propia,
   token de Coolify nuevo, politica completada con los volumenes anonimos que crean el
   DR y los redespliegues, timers, backup). Verificar con `vps-backup status` y
   `vps-backup check`. Luego desactivar los timers de vps-backup en vps-01.
8. **Comprobar:** login en Vaultwarden, envio y recepcion de correo, certificado de
   Mailu (`/usr/local/bin/mailu-cert-sync.sh` cuando Traefik tenga el de
   `mail.quisqueyatech.com`), n8n, Firefly, MeshCentral (los agentes reconectan solos
   al cambiar el DNS de `mesh`).

## Corte realizado (2026-11-24)

Backup final de vps-01 `75b91623` (22:41); DR en vps-02, `go-live`, DNS en Cloudflare
(8 registros A de las dos zonas + SPF, con el CLI `cf`), PTR en el panel de Contabo
(`cntb` no gestiona DNS inverso) y `finish`; primer backup propio correcto (23:17).
vps-01 con todos sus contenedores parados (lista en
`~julio-marte/cutover-running-20261124.txt`).

Lecciones para la proxima vez:

- Coolify rearranca `coolify-proxy` aunque se pare con `docker stop` (lo hizo a los
  pocos minutos, durante el backup final). Parar tambien el contenedor `coolify`
  justo despues del snapshot de sistema, o vigilarlo.
- Traefik pide los certificados al arrancar, antes del cambio de DNS, y falla; tras
  cambiar el DNS: `docker restart coolify-proxy` (obtuvo los 11 al momento).
- Mailu: `live/npm-2/fullchain.pem` y `privkey.pem` venian de vps-01 como ficheros
  sueltos con un certificado caducado, no como enlaces a `archive/npm-2/*4.pem`, asi que
  `mailu-cert-sync.sh` actualizaba ficheros que el front no lee ("no shared cipher" en
  993/587/25). Arreglo: enlaces a `../../archive/npm-2/fullchain4.pem` y
  `privkey4.pem` y `docker restart` del front (los antiguos en `/root/mailu-certs-old`).
- Con el proxy de Cloudflare los registros web cambian al instante; `mail`, `mesh` y el
  resto salen del comodin `*` (sin proxy, TTL automatico de 300 s): no hizo falta bajar
  TTL con 24 h de antelacion.

## Despues

- Netdata: `/root/cutover/vps02-cutover.sh netdata` instala el agente con la
  configuracion y el claim de vps-01 y el watchdog de ACLK. vps-02 entra como nodo
  propio en el mismo espacio de Netdata Cloud (no se copia la identidad de nodo de
  vps-01). Puede hacerse antes del corte. Al apagar vps-01, quitar su nodo en Cloud.
- HetrixTools no se reinstala (decision 2026-11-24).
- El exit de `local-proxy` (crontab de julio-marte en vps-01) sigue en vps-01 mientras
  exista; moverlo es una decision aparte.
- vps-01 pasa a ser el host de backup cuando se decida; su repositorio
  `vmi2741977` conserva el historial anterior al corte.

## Riesgos conocidos

- Sin alertas: ningun host tiene hooks `failure.d` ni healthchecks; un backup que falla
  no avisa a nadie. Conviene un ping a healthchecks.io (o ntfy) en `post-backup.d` y
  `failure.d`.
- Volumenes anonimos (`VOLUME` del Dockerfile): reciben un nombre nuevo en cada
  recreacion, asi que el DR los restaura con el nombre de vps-01 y nadie los monta.
  Afecta a `the-vocal-room-academy` (su SQLite y `receipts/`: cada redeploy empieza
  con un volumen vacio, tambien en vps-01; hoy solo tiene datos semilla) y a la cola
  de Postfix de Mailu. Solucion: volumen con nombre en Coolify para esas rutas.
- Imagenes: el DR fija cada imagen al digest del origen si el backup trae
  `image-digests.tsv` (hook 45, instalado en vps-01 desde `72c57274`). Usar ese
  snapshot o uno posterior; los anteriores no traen digests ni copias consistentes.
- Las pruebas de restore desde vps-02 contra el repositorio de vps-01 pueden dejar un
  lock abandonado (paso el 2026-11-23); `restic unlock` desde vps-02 lo quita.
