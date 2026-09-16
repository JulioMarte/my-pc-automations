$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'watchdog.log'

function Write-WatchdogLog([string]$Message) {
  Add-Content -LiteralPath $logFile -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

function Get-EnvValue([string]$Name, [string]$Default) {
  $envFile = Join-Path $root '.env'
  if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
      if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(\S+)')) { return $Matches[1].Trim() }
    }
  }
  return $Default
}

# Sonda HTTP real del servicio, con timeout corto.
function Test-Http([string]$Url, [int]$TimeoutSeconds = 5) {
  try {
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Method = 'GET'
    $request.Timeout = $TimeoutSeconds * 1000
    $request.ReadWriteTimeout = $TimeoutSeconds * 1000
    $request.AllowAutoRedirect = $true
    $response = $request.GetResponse()
    $code = [int]$response.StatusCode
    $response.Close()
    return ($code -ge 200 -and $code -lt 400)
  } catch {
    return $false
  }
}

function Get-RunnerProcess {
  return @(Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'proxy-autostart\.ps1' })
}

function Stop-PidFileProcesses {
  $pidFile = Join-Path $logDir 'autostart.pids'
  if (-not (Test-Path -LiteralPath $pidFile)) { return }
  foreach ($line in Get-Content -LiteralPath $pidFile) {
    $processId = 0
    if (-not [int]::TryParse($line.Trim(), [ref]$processId)) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($process -and $process.Name -eq 'node.exe') {
      Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
  }
}

# Sondas de salud del servicio real (no del runner).
$gatewayHost = Get-EnvValue 'GATEWAY_HOST' '127.0.0.1'
$gatewayPort = [int](Get-EnvValue 'GATEWAY_HTTP_PORT' '8888')
$gatewayUrl = "http://${gatewayHost}:${gatewayPort}/healthz"

$exitHost = Get-EnvValue 'EXIT_HOST' ''
$exitPortText = Get-EnvValue 'EXIT_PORT' ''
$exitUrl = ''
if ($exitHost -and $exitPortText) {
  $exitUrl = "http://${exitHost}:$([int]$exitPortText)/__health"
}

$gatewayHealthy = Test-Http $gatewayUrl 5
$exitHealthy = $true
if ($exitUrl) { $exitHealthy = Test-Http $exitUrl 5 }

if ($gatewayHealthy -and $exitHealthy) {
  Write-WatchdogLog "sano (gateway=$gatewayHealthy exit=$exitHealthy)"
  exit 0
}

$runner = Get-RunnerProcess

if (-not $runner -or $runner.Count -eq 0) {
  Write-WatchdogLog "servicio no sano (gateway=$gatewayHealthy exit=$exitHealthy) y runner ausente; inicio tarea local-proxy-autostart"
  try {
    Start-ScheduledTask -TaskName 'local-proxy-autostart' -ErrorAction Stop
  } catch {
    Write-WatchdogLog "no pude iniciar la tarea: $($_.Exception.Message)"
  }
  exit 0
}

# Runner vivo pero servicio colgado: reinicio limpio.
Write-WatchdogLog "servicio no sano (gateway=$gatewayHealthy exit=$exitHealthy) con runner vivo (pid=$($runner[0].ProcessId)); reinicio"
try {
  Stop-ScheduledTask -TaskName 'local-proxy-autostart' -ErrorAction Stop
} catch {
  Write-WatchdogLog "no pude detener la tarea: $($_.Exception.Message)"
}
Stop-PidFileProcesses
Start-Sleep -Seconds 2
try {
  Start-ScheduledTask -TaskName 'local-proxy-autostart' -ErrorAction Stop
} catch {
  Write-WatchdogLog "no pude relanzar la tarea: $($_.Exception.Message)"
}
