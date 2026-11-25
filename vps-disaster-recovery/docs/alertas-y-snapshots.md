# Alertas de backup y snapshots de Contabo

Herramientas de `ops/` instaladas en vps-02 (2026-11-25) con `ops/install.sh`.

## Alertas (ntfy)

- `vps-alert <prioridad> <titulo> <mensaje>`: aviso a un topic de ntfy.sh (sin
  cuenta). El topic aleatorio vive en `/etc/vps-backup/alert.env` (0600) y es el unico
  secreto: quien lo conozca lee y publica avisos. No se versiona. Los mensajes llevan
  solo host, unidad y estado, nunca logs.
- **Fallo de unidad**: drop-in `OnFailure=vps-alert-failed@%n.service` en
  `vps-backup`, `vps-backup-maintenance`, `vps-backup-dr-test` y `vps-snapshot`.
- **Backups caducados** (`vps-backup-freshness.timer`, cada hora): lee el repositorio
  (no logs locales) y avisa si el ultimo snapshot `system` o `docker-volumes` del host
  tiene 8 h o mas, o si el repositorio no responde. Avisa al empezar, cada 24 h
  mientras siga y una vez al recuperarse. Cubre tambien un timer desactivado o un
  backup que nunca termina, que `OnFailure` no ve.
- **Host caido**: no lo puede avisar el propio host. Lo cubre Netdata Cloud (nodo
  inalcanzable). Comprobar que esas notificaciones estan activas en la cuenta.

Para recibirlos: app ntfy (Android/iOS) o https://ntfy.sh, suscribirse al topic.

## Snapshots de Contabo

`vps-snapshot` usa un usuario de API con el rol `vps02-snapshots-solo` (id 108824):
solo crear/listar snapshots y ver/borrar uno, y solo en recursos con la etiqueta
`vps02-snapshots` (id 201644, asignada a vmi3456423). Sin rollback, parada,
reinstalacion ni acceso a otros VPS: volver a un snapshot es manual desde el panel,
asi que un intruso en vps-02 no puede usar esta credencial para pisar el servidor.

- `vps-snapshot crear --con-backup "actualizar coolify"`: antes de cualquier cambio
  arriesgado. `--con-backup` hace antes un backup de Restic (las SQLite quedan
  consistentes alli; en el snapshot el disco se copia en caliente).
- `vps-snapshot semanal`: domingo hacia las 03:45, tras el backup de las 03:00.
- Rotacion: con `SNAPSHOT_MAX` (2) snapshots o mas, borra el mas antiguo **creado por
  la herramienta** (prefijo `vps-snap-`); nunca los hechos a mano en el panel.
- `vps-snapshot comprobar`: credenciales y alcance (solo lecturas; nunca prueba una
  accion peligrosa para ver si esta prohibida).

Un snapshot no sustituye a Restic: mismo proveedor y mismo centro de datos, y al
volver a el se pierde todo lo escrito despues. Sirve para "la actualizacion lo
rompio": volver en minutos en lugar de un DR de ~45 min.

### Alta del usuario (manual, una vez)

La API exige un correo por usuario y la contrasena la pone el titular:

1. Panel de Contabo > Usuarios: crear usuario con el rol `vps02-snapshots-solo`.
2. Fijar su contrasena de API.
3. En vps-02, completar `/etc/vps-backup/contabo.env` (client id/secret de la cuenta,
   correo y contrasena de ese usuario, `CONTABO_INSTANCE_ID=203456423`).
4. `vps-snapshot comprobar` y `ops/install.sh` de nuevo (activa el timer).

## Pendiente (no implementado)

- Copia de los backups que vps-02 no pueda borrar (Object Lock o segundo proveedor
  con credenciales fuera de vps-02). Hoy las claves de R2 en vps-02 permiten borrar.
- Ensayo automatico del DR (p. ej. nocturno en vps-01) y procedimiento para
  restaurar vps-02 desde sus propios snapshots.
