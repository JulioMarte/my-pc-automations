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

## Antes del dia del corte

1. En vps-01 (lo hace quien tenga sudo alli): instalar los hooks del repo
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
   `postgres-sql-postgres-1` (fuera de Coolify) se recrea a mano como en la prueba:
   red `web_network`, volumen `postgres_data`, `postgres:16.4`, `globals.sql` y
   `restore_builtin_postgres_container` con el dump del bundle.
5. **Abrir salida:** `/root/cutover/vps02-cutover.sh go-live`.
6. **DNS:** apuntar a vps-02 (A 144.126.139.118, AAAA 2605:a140:2345:6423::1) cada
   dominio que sirve Coolify. La lista sale de su base de datos (no se versiona aqui:
   el repositorio es publico):
   `docker exec -i coolify-db psql -At -U coolify -d coolify -c "select fqdn from applications where deleted_at is null union all select fqdn from service_applications where deleted_at is null" | tr , '\n' | sed -E 's#^https?://##; s#[:/].*##' | sort -u`
   Correo: SPF con `ip4:144.126.139.118` (y `ip6:` si se usa) en lugar de la IP de
   vps-01; PTR de 144.126.139.118 -> `mail.quisqueyatech.com` en Contabo. DKIM no
   cambia (la clave viene en el volumen `mailu_mailu_dkim`).
7. **Backups de vps-02:** `/root/cutover/vps02-cutover.sh finish` (identidad propia,
   token de Coolify nuevo, timers, backup). Verificar con `vps-backup status` y
   `vps-backup check`. Luego desactivar los timers de vps-backup en vps-01.
8. **Comprobar:** login en Vaultwarden, envio y recepcion de correo, certificado de
   Mailu (`/usr/local/bin/mailu-cert-sync.sh` cuando Traefik tenga el de
   `mail.quisqueyatech.com`), n8n, Firefly, MeshCentral (los agentes reconectan solos
   al cambiar el DNS de `mesh`).

## Despues

- Reinstalar en vps-02 lo que vive en el host y no restaura el DR: agente de Netdata
  (y `/usr/local/bin/netdata-aclk-watchdog.sh` en el crontab de root), HetrixTools, y
  el exit de `local-proxy` (crontab de julio-marte en vps-01).
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
  `image-digests.tsv` (hook 45). Sin ese hook en vps-01, Coolify descarga lo que la
  etiqueta sea ese dia.
