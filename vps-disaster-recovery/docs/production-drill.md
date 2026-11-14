# Prueba real de aceptación en VPS

Este runbook valida el candidato **v1.4.3** contra infraestructura real sin
destruir el VPS de producción que origina los backups.

## Regla de aceptación

La prueba se considera aprobada solo si se cumplen los tres bloques:

1. **Backup real** desde el VPS origen hacia el S3 real.
2. **Restore real** en un VPS desechable distinto.
3. **Validación funcional** de los datos y servicios antes de cualquier cutover.

No se destruye el VPS origen durante la primera prueba. Una prueba de pérdida
total puede hacerse después de que este drill pase al menos una vez.

## 1. Verificar el release bundle

En el host desde el que copies el artefacto:

```bash
sha256sum -c SHA256SUMS
chmod 0755 vps-backup-v1.4.3.sh
./vps-backup-v1.4.3.sh version
```

Debe devolver exactamente:

```text
vps-backup v1.4.3
```

## 2. Backup en el VPS origen

Instala el candidato y usa inicialmente el perfil `balanced` salvo que el RPO
real del workload exija otra política.

```bash
sudo ./vps-backup-v1.4.3.sh install
sudo vps-backup doctor
sudo vps-backup backup
sudo vps-backup dr-plan
sudo vps-backup dr-test
sudo vps-backup status
```

No continúes si `doctor`, `backup`, `dr-plan` o `dr-test` fallan.

Para Coolify:

```bash
sudo vps-backup coolify-policy audit
```

Guarda además fuera del VPS:

- BACKUP_ID.
- endpoint, región, bucket y prefijo S3.
- recovery key S3.
- contraseña Restic.
- APP_KEY de Coolify como copia secundaria de emergencia.

El backup de instancia de Coolify no contiene los datos de aplicaciones,
databases o volumes; esas capas deben aparecer protegidas en `dr-plan`.

## 3. Snapshot Contabo opcional

Un snapshot de Contabo es un acelerador de rollback, no el backup autoritativo.

Primero:

```bash
sudo vps-backup provider contabo snapshot --dry-run
```

Solo si el dry-run valida slots y política:

```bash
sudo vps-backup provider contabo snapshot --prune
sudo vps-backup provider contabo status
```

La política segura exige `KEEP < SLOT_LIMIT` para reservar un slot. No uses
rotación automática con un plan de un solo slot.

## 4. VPS destino desechable

Crea un VPS nuevo con el mismo `ID`, `VERSION_ID` y arquitectura del origen.
No apuntes DNS de producción al VPS nuevo todavía.

Copia el release bundle y verifica SHA-256 de nuevo.

Ejecuta primero solo el plan:

```bash
sudo ./vps-backup-v1.4.3.sh recovery-bootstrap \
  --require-same-os
```

Para automatización se recomienda un archivo root-only para la contraseña
Restic y variables de entorno efímeras para la recovery key S3. No pongas
secretos en argumentos de línea de comandos.

Cuando el plan quede verde, ejecuta la recuperación usando el snapshot exacto
que acabas de validar:

```bash
sudo vps-backup recovery-bootstrap \
  --require-same-os \
  --execute \
  --snapshot SNAPSHOT_ID
```

### Limitación deliberada del modo genérico same-OS

El modo portable same-OS restaura configuración y paths portables, pero no
clona bootloader, networking del proveedor, machine-id, SSH host keys,
`/var/lib/docker` ni data directories físicas de databases.

Workloads genéricos que necesiten recrear containers/services antes de inyectar
datos deben tener un `restore.d` probado. La ruta Coolify tiene orquestación
específica adicional para control plane, databases declaradas, volumes y hooks.

## 5. Ruta QCOW2

La QCOW2 de recuperación es una imagen limpia, no una imagen del disco vivo.

```bash
sudo ./tools/build-recovery-image.sh \
  --output ./vps-recovery-ubuntu-24.04-amd64.qcow2
qemu-img check ./vps-recovery-ubuntu-24.04-amd64.qcow2
```

Contabo admite ISO y QCOW2 para Custom Images. Para este proyecto se usa QCOW2
porque representa un disco arrancable ya preparado; ISO se reserva para medios
de instalación. La imagen debe ser x86-64 y soportar VirtIO.

La imagen no debe contener credenciales S3, contraseña Restic, APP_KEY ni SSH
private keys.

## 6. Validaciones antes de tráfico

Como mínimo:

```bash
sudo vps-backup doctor
sudo vps-backup dr-plan --snapshot SNAPSHOT_ID
systemctl --failed
docker ps --format 'table {{.Names}}\t{{.Status}}'
df -h
```

Para Coolify confirma además:

- dashboard accesible;
- `Servers > localhost` valida;
- projects/resources esperados presentes;
- databases restauradas;
- persistent storage restaurado;
- ningún container crítico unhealthy/exited;
- login y al menos una operación funcional de cada aplicación crítica.

Compara checksums/contadores conocidos de databases y archivos del fixture.

## 7. Criterio final

Solo declara:

```text
PRODUCTION DR VALIDATED
```

cuando el backup provenga del S3 real y el restore se haya completado en un VPS
diferente usando los mismos bytes del release candidate cuyo SHA aparece en
`SHA256SUMS`.

El DNS/cutover permanece manual y separado de esta prueba.

## Referencias operativas

- Coolify instance backup/restore:
  https://coolify.io/docs/core/backup-and-recovery/instance-backup
  https://coolify.io/docs/core/backup-and-recovery/instance-restore
- Contabo Custom Images:
  https://help.contabo.com/en/support/solutions/articles/103000274171-can-i-use-custom-images-on-my-server-
- Contabo snapshots:
  https://help.contabo.com/en/support/solutions/articles/103000270385-how-do-i-create-a-snapshot-of-my-server-
