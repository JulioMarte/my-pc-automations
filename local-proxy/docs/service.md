# Servicio real (systemd / Windows Service) - OPCIONAL

Esta guia describe el camino **adicional y opcional** para correr `local-proxy` como
**servicio real del sistema operativo**:

- **Linux**: unidades **systemd** (`service/systemd/`).
- **Windows**: **Windows Service** con **WinSW v2.12.0** (`service/windows/`).

No reemplaza a los mecanismos existentes (Task Scheduler en Windows, cron +
`scripts/exit-daemon.sh` en Linux). Es una alternativa para quien quiera que el SO
supervise el proceso (reinicio nativo, arranque al bootear, logs centralizados).

---

## Cuando usar un servicio real y cuando no

| Escenario | Mecanismo recomendado |
|---|---|
| Windows sin admin, arranque al iniciar sesion | Task Scheduler sin admin (`npm run autostart:install`) |
| Windows con admin, arranque al encender sin login | Task Scheduler como SYSTEM (`scripts/install-autostart-admin.ps1`) |
| Windows con admin y quieres reinicio nativo del SO + logs por servicio | **WinSW** (`service/windows/`) |
| VPS/Linux sin sudo | cron + `scripts/exit-daemon.sh` |
| VPS/Linux con root y quieres reinicio nativo (`Restart=always`) | **systemd** (`service/systemd/`) |
| Quieres instalar sin root en Linux | **systemd `--user`** + `loginctl enable-linger` (ver abajo) |

Regla practica: usa servicio real si tienes root/admin y quieres que el **SO** maneje
reinicios y arranque al boot. Si no tienes privilegios, quedate con el mecanismo viejo.

---

## Linux: systemd

### Requisitos

- systemd (la mayoria de VPS modernos).
- Root (o `sudo`) para unidades de sistema.
- Node 22+ en `/usr/bin/node` (el `ExecStart` lo asume; si tu Node esta en otro lado,
  edita la unit generada o crea un enlace simbolico en `/usr/bin/node`).
- La build hecha: `dist/gateway.js` y/o `dist/exit.js` (`npm run build`).
- Tailscale corriendo (`tailscaled.service`): las units usan `After=`/`Wants=`.

### Instalar

Desde la raiz del proyecto:

```bash
sudo service/systemd/install.sh          # gateway + exit
sudo service/systemd/install.sh all
sudo service/systemd/install.sh gateway
sudo service/systemd/install.sh exit
```

El script:

1. Sustituye `__PROJECT_DIR__` por la ruta absoluta del proyecto.
2. Escribe `/etc/systemd/system/local-proxy-<rol>.service`.
3. Ejecuta `systemctl daemon-reload` y `systemctl enable --now`.

Es idempotente: puedes re-ejecutarlo. Si la unit ya estaba activa y cambiaste el
archivo, aplica el cambio con `sudo systemctl restart local-proxy-<rol>.service`.

### Estado y logs

```bash
systemctl status local-proxy-gateway.service
systemctl status local-proxy-exit.service

systemctl is-active  local-proxy-gateway.service
systemctl is-enabled local-proxy-gateway.service

journalctl -u local-proxy-gateway.service -f
journalctl -u local-proxy-exit.service -f
journalctl -u local-proxy-gateway.service --since '10 min ago'
```

### Desinstalar

```bash
sudo systemctl disable --now local-proxy-gateway.service
sudo systemctl disable --now local-proxy-exit.service
sudo rm -f /etc/systemd/system/local-proxy-gateway.service \
           /etc/systemd/system/local-proxy-exit.service
sudo systemctl daemon-reload
```

### Alternativa sin root: `systemctl --user`

Si no tienes root, puedes instalar las unidades en tu usuario. Requiere que el
usuario pueda mantener procesos vivos sin sesion abierta: `loginctl enable-linger`.

```bash
mkdir -p ~/.config/systemd/user

# Copia y sustituye el placeholder manualmente (o reutiliza el script con UNIT_DIR).
sed 's|__PROJECT_DIR__|'"$PWD"'|g' \
  service/systemd/local-proxy-gateway.service \
  > ~/.config/systemd/user/local-proxy-gateway.service

systemctl --user daemon-reload
systemctl --user enable --now local-proxy-gateway.service

# Mantener el servicio vivo sin sesion (y al bootear):
sudo loginctl enable-linger "$USER"

# Estado / logs
systemctl --user status local-proxy-gateway.service
journalctl --user -u local-proxy-gateway.service -f
```

Nota: `systemctl --user` no tiene `After=tailscaled.service` garantizado (Tailscale
suele ser un servicio de sistema). El proceso de Node no necesita Tailscale para
arrancar, pero no tendra conectividad hasta que Tailscale este arriba.

---

## Windows: Windows Service con WinSW v2.12.0

WinSW es un "wrapper": renombras `WinSW-x64.exe` a `gateway-service.exe`, pones al
lado `gateway-service.xml` (mismo nombre base) y ejecutas `gateway-service.exe install`
y `start`. El servicio queda registrado y el SO lo reinicia si falla.

### Requisitos

- Consola **elevada** (Administrador) para instalar/desinstalar.
- Node 22+ instalado (el script resuelve la ruta real de `node.exe`).
- La build hecha (`npm run build`).
- Tailscale arriba (el servicio no lo espera explicitamente; ver "Interaccion" abajo).
- Descarga de WinSW desde GitHub (solo la primera vez).

### Instalar

```powershell
powershell -ExecutionPolicy Bypass -File service\windows\install-windows-service.ps1
powershell -ExecutionPolicy Bypass -File service\windows\install-windows-service.ps1 -Role gateway
powershell -ExecutionPolicy Bypass -File service\windows\install-windows-service.ps1 -Role exit
```

El script:

1. Exige Administrador (si no, falla con un mensaje claro).
2. Descarga `WinSW-x64.exe` (o `-x86`) v**2.12.0** en `service\windows\` si falta.
3. Genera `service\windows\runtime\<rol>-service.xml` desde la plantilla, sustituyendo
   `{{NODE}}` y `{{PROJECT_DIR}}`, y copia el exe de WinSW como
   `service\windows\runtime\<rol>-service.exe`.
4. Instala y arranca el servicio (`install`, `start`). Si ya existia, lo reinstala.

Es idempotente: re-ejecutarlo reinstala el servicio con la configuracion nueva.

### Estado y logs

```powershell
Get-Service local-proxy-gateway, local-proxy-exit | Format-Table Name,Status,StartType
Get-Service local-proxy-gateway | Select-Object -ExpandProperty Status

# Control manual
service\windows\runtime\gateway-service.exe status
service\windows\runtime\gateway-service.exe restart
service\windows\runtime\gateway-service.exe stopwait
```

Logs (stdout/stderr del proceso Node):

- `logs\gateway-service.out.log` / `logs\gateway-service.err.log`
- `logs\exit-service.out.log` / `logs\exit-service.err.log`

Errores del propio wrapper de Windows van al **Visor de eventos** (Origen: `local-proxy-gateway`).

### Desinstalar

```powershell
powershell -ExecutionPolicy Bypass -File service\windows\uninstall-windows-service.ps1
powershell -ExecutionPolicy Bypass -File service\windows\uninstall-windows-service.ps1 -Role gateway
```

Detiene y desregistra el servicio. **No borra** logs ni el directorio `runtime\`.

---

## Tradeoffs y advertencias honestas

- **Necesita privilegios**: root/sudo en Linux, Administrador en Windows. Es el precio
  de un servicio real. Si no los tienes, usa el mecanismo viejo.
- **WinSW es un binario externo** (v2.12.0, ~18 MB) descargado de GitHub. WinSW **no
  publica un SHA256 oficial** en su release, asi que el script **no fija un hash**:
  valida que sea un PE valido (cabecera `MZ`), no vacio, y avisa del estado de la
  firma Authenticode. Si tienes el hash, pasalo con `-ExpectedSha256 <HEX>`.
  Dato observado (no oficial) para `WinSW-x64.exe` v2.12.0, descargado el 2026-09-16
  (`18.243.033` bytes): `05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA`.
  Verificalo tu mismo antes de confiar en el; el binario nativo x64 viene **NotSigned**
  (sin firma Authenticode), por eso el script avisa. El exe y la config generada quedan
  ignorados por git (`service/windows/.gitignore`).
- **Tailscale tiene que estar arriba**. En Linux las units lo piden con
  `After=`/`Wants=tailscaled.service`, pero eso no bloquea indefinidamente: el proceso
  puede arrancar antes y quedarse sin conectividad hasta que Tailscale suba. En Windows
  el wrapper no espera a Tailscale; el proceso Node reintenta y el health check se
  recupera cuando hay red. En el gateway, si el health check depende de Tailscale,
  `/readyz` puede tardar en ponerse en verde.
- **No dupliques mecanismos**. El arranque viejo (Task Scheduler / cron) y el servicio
  nuevo **no se conocen**. Si dejas ambos, tendras **dos instancias** de Node peleando
  por los mismos puertos. **Desactiva el viejo antes**:
  - Windows: `npm run autostart:uninstall` (o `scripts\uninstall-autostart.ps1`) desde
    una consola elevada si se registraron como SYSTEM, y confirma que no queda ninguna
    tarea `local-proxy-autostart` / `local-proxy-watchdog`.
  - Linux: quita las lineas `@reboot` y `*/2 * * * *` de `crontab -e` que llaman a
    `scripts/exit-daemon.sh`.
- **El watchdog viejo no vigila el servicio nuevo**. `scripts/proxy-watchdog.ps1` esta
  pensado para el runner de Task Scheduler. Con WinSW/systemd, el reinicio nativo
  (`onfailure` en WinSW, `Restart=always` en systemd) es el que supervisa. Si dejas el
  watchdog activo, podria matar procesos del servicio nuevo: **no mezcles**.
- **Cambiar la configuracion**:
  - systemd: edita el `.env` (se recarga en caliente para usuarios/tokens) o la unit y
    luego `sudo systemctl daemon-reload && sudo systemctl restart local-proxy-<rol>`.
  - WinSW: re-ejecuta `install-windows-service.ps1` (regenera el XML y reinstala).
- **Reinicio nativo no es magia**: `onfailure action="restart"` y `Restart=always`
  reinician el proceso, pero no arreglan una mala configuracion. Revisa los logs.
