#Requires -RunAsAdministrator
<#
  Arranque REAL al encender la PC, sin necesidad de iniciar sesion.
  Requiere ejecutarse una vez en una consola elevada (Administrador):

    powershell -ExecutionPolicy Bypass -File scripts\install-autostart-admin.ps1

  Registra las tareas para que corran como SYSTEM: sobreviven reinicios y no
  dependen de que alguien inicie sesion.
#>
param(
  [string]$Roles = 'exit,gateway',
  [string]$TaskName = 'local-proxy-autostart',
  [string]$WatchdogName = 'local-proxy-watchdog'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot 'proxy-autostart.ps1'
$watchdog = Join-Path $PSScriptRoot 'proxy-watchdog.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw "no existe $runner" }
if (-not (Test-Path -LiteralPath $watchdog)) { throw "no existe $watchdog" }

function Find-Npm {
  $command = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $command) { $command = Get-Command npm -ErrorAction SilentlyContinue }
  if ($command) { return $command.Source }
  return $null
}

# La build debe existir antes de registrar las tareas.
function Ensure-Build {
  $entry = Join-Path $root 'dist\exit.js'
  if (Test-Path -LiteralPath $entry) { return }
  Write-Output 'dist\exit.js no existe; ejecutando npm run build...'
  $npm = Find-Npm
  if (-not $npm) { throw 'npm no encontrado en PATH; no puedo construir dist' }
  Push-Location -LiteralPath $root
  try {
    & $npm run build
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  if ($code -ne 0) { throw "npm run build fallo (exit=$code); no registro las tareas" }
  if (-not (Test-Path -LiteralPath $entry)) { throw 'la build no genero dist\exit.js' }
}

Ensure-Build

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# Tarea principal: al arrancar Windows (AtStartup), con reintento si el runner muere.
$mainSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$mainAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -Roles $Roles"
$mainTrigger = New-ScheduledTaskTrigger -AtStartup

Register-ScheduledTask -TaskName $TaskName -Action $mainAction -Trigger $mainTrigger `
  -Settings $mainSettings -Principal $principal `
  -Description 'local-proxy: exit + gateway al arrancar Windows (SYSTEM, sin login)' -Force | Out-Null

# Watchdog: cada 2 minutos, aunque nadie haya iniciado sesion.
$watchdogSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
$watchdogAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdog`""
$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $WatchdogName -Action $watchdogAction -Trigger $watchdogTrigger `
  -Settings $watchdogSettings -Principal $principal `
  -Description 'local-proxy: revisa cada 2 minutos la salud del servicio (SYSTEM)' -Force | Out-Null

Write-Output "OK: '$TaskName' arranca con Windows (SYSTEM) y '$WatchdogName' vigila cada 2 minutos."
Write-Output "Esto sobrevive reinicios aunque nadie inicie sesion."

$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Add-Content -LiteralPath (Join-Path $logDir 'install-admin.log') -Value (
  "{0} tareas SYSTEM registradas: {1}, {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $TaskName, $WatchdogName
)
