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

# Tarea principal: al iniciar sesion, con reintento automatico si el runner muere.
$mainSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$mainAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`" -Roles $Roles"
$mainTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

Register-ScheduledTask -TaskName $TaskName -Action $mainAction -Trigger $mainTrigger `
  -Settings $mainSettings -Description 'local-proxy: exit + gateway al iniciar sesion (con reintento)' -Force | Out-Null

# Watchdog: cada 2 minutos, revive el runner si murio (trigger Once + repeticion, fiable).
$watchdogSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
$watchdogAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdog`""
$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $WatchdogName -Action $watchdogAction -Trigger $watchdogTrigger `
  -Settings $watchdogSettings -Description 'local-proxy: revisa cada 2 min la salud del servicio' -Force | Out-Null

Write-Output "Tarea '$TaskName' registrada al iniciar sesion para $env:USERNAME (roles: $Roles)."
Write-Output "Watchdog '$WatchdogName' registrado cada 2 minutos."
Write-Output "Iniciar ahora: Start-ScheduledTask -TaskName '$TaskName'"
