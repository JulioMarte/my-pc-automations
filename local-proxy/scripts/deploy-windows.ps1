#Requires -RunAsAdministrator
<#
  Despliegue del build (dist/) en Windows:
  detiene las tareas, mata runner + nodos (src o dist), limpia lock/pid,
  reconstruye, arranca la tarea principal y habilita el watchdog.
  Ejecutar como administrador.
#>
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'deploy.log'

function Log([string]$Message) {
  Add-Content -LiteralPath $logFile -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

Log 'deploy: inicio'

# Drenado best-effort ANTES de detener: pide al gateway que deje terminar los tuneles en
# vuelo (POST /__drain). Si STATS_TOKEN esta vacio o el gateway no responde, se ignora.
$envFile = Join-Path $root '.env'
$gatewayHost = $null
$gatewayPort = $null
$statsToken = $null
if (Test-Path -LiteralPath $envFile) {
  foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*GATEWAY_HOST\s*=\s*(.+?)\s*$') { $gatewayHost = $Matches[1].Trim() }
    if ($line -match '^\s*GATEWAY_HTTP_PORT\s*=\s*(.+?)\s*$') { $gatewayPort = $Matches[1].Trim() }
    if ($line -match '^\s*STATS_TOKEN\s*=\s*(.+?)\s*$') { $statsToken = $Matches[1].Trim() }
  }
}
if ($statsToken -and $gatewayHost -and $gatewayPort) {
  $drainUrl = "http://{0}:{1}/__drain?token={2}" -f $gatewayHost, $gatewayPort, $statsToken
  Log 'drain: POST /__drain (best-effort)'
  try {
    Invoke-WebRequest -Uri $drainUrl -Method Post -TimeoutSec 3 -UseBasicParsing | Out-Null
    Log 'drain: ok'
  } catch {
    Log ("drain: ignorado ({0})" -f $_.Exception.Message)
  }
} else {
  Log 'drain: omitido (STATS_TOKEN/GATEWAY_HOST/GATEWAY_HTTP_PORT vacios)'
}

Stop-ScheduledTask -TaskName 'local-proxy-autostart' -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName 'local-proxy-watchdog' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $_.CommandLine -match 'proxy-autostart\.ps1' -or $_.CommandLine -match '(src|dist)[\\/](exit|gateway)\.js'
}
foreach ($target in $targets) {
  Log ("matando pid={0} {1}" -f $target.ProcessId, $target.Name)
  Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

Remove-Item -LiteralPath (Join-Path $logDir 'autostart.lock') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $logDir 'autostart.pids') -Force -ErrorAction SilentlyContinue

$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source }
if ($npm) {
  Log 'build: npm run build'
  & $npm run build *>> (Join-Path $logDir 'build.log')
  Log ("build exit={0}" -f $LASTEXITCODE)
} else {
  Log 'npm no encontrado; asumo dist ya construido'
}

Start-ScheduledTask -TaskName 'local-proxy-autostart' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 8
Enable-ScheduledTask -TaskName 'local-proxy-watchdog' -ErrorAction SilentlyContinue
Log 'deploy: tarea iniciada y watchdog habilitado'
Log 'deploy: fin'
