param(
  [string]$Roles = 'exit,gateway'
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$pidFile = Join-Path $logDir 'autostart.pids'
$lockFile = Join-Path $logDir 'autostart.lock'

function Write-Log([string]$Message) {
  $logFile = Join-Path $logDir ("autostart-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))
  Add-Content -LiteralPath $logFile -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

# --- candado: un solo runner a la vez ---
if (Test-Path -LiteralPath $lockFile) {
  $lockPid = 0
  $lockText = Get-Content -LiteralPath $lockFile -First 1 -ErrorAction SilentlyContinue
  if ([int]::TryParse(([string]$lockText).Trim(), [ref]$lockPid)) {
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $lockPid" -ErrorAction SilentlyContinue
    if ($existing -and $existing.CommandLine -match 'proxy-autostart\.ps1') {
      Write-Log "ya hay un runner activo (pid=$lockPid); salgo"
      exit 0
    }
  }
}
Set-Content -LiteralPath $lockFile -Value $PID

function Find-Node {
  $command = Get-Command node -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $candidates = @(
    (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe')
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  throw 'node.exe no encontrado en PATH ni en las rutas tipicas'
}

function Find-Npm {
  $command = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $command) { $command = Get-Command npm -ErrorAction SilentlyContinue }
  if ($command) { return $command.Source }
  return $null
}

# La build debe existir antes de arrancar los roles.
function Ensure-Build {
  $missing = @()
  foreach ($role in @('exit', 'gateway')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root ("dist\{0}.js" -f $role)))) { $missing += $role }
  }
  if (-not $missing.Count) { return }
  Write-Log ("falta dist ({0}); ejecutando npm run build" -f ($missing -join ', '))
  $npm = Find-Npm
  if (-not $npm) {
    Write-Log 'npm no encontrado; no puedo construir dist; aborto'
    exit 1
  }
  & $npm run build 2>&1 | Add-Content -LiteralPath (Join-Path $logDir 'build.log')
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    Write-Log ("npm run build fallo (exit={0}); aborto" -f $code)
    exit 1
  }
  foreach ($role in @('exit', 'gateway')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root ("dist\{0}.js" -f $role)))) {
      Write-Log ("la build no genero dist\{0}.js; aborto" -f $role)
      exit 1
    }
  }
  Write-Log 'build completada'
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

function Get-RoleEndpoint([string]$Role) {
  if ($Role -eq 'gateway') {
    return @{ Host = (Get-EnvValue 'GATEWAY_HOST' '127.0.0.1'); Port = [int](Get-EnvValue 'GATEWAY_HTTP_PORT' '8888') }
  }
  return @{ Host = (Get-EnvValue 'EXIT_HOST' '127.0.0.1'); Port = [int](Get-EnvValue 'EXIT_PORT' '8899') }
}

# Sonda TCP barata con timeout, para detectar procesos vivos pero colgados.
function Test-Port([string]$HostName, [int]$Port, [int]$TimeoutMs = 3000) {
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $async = $client.BeginConnect($HostName, $Port, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
    $client.EndConnect($async)
    return $true
  } catch {
    return $false
  } finally {
    $client.Close()
  }
}

# Backoff exponencial con jitter completo: random(0, min(60, 2 * 2^fallos)).
function Get-BackoffDelay([int]$Failures) {
  $exp = [math]::Min($Failures, 6)
  $ceiling = [math]::Min(60, 2 * [math]::Pow(2, $exp))
  $max = [int][math]::Floor($ceiling)
  if ($max -lt 1) { return 0 }
  return Get-Random -Minimum 0 -Maximum ($max + 1)
}

function Stop-StaleProcesses {
  if (-not (Test-Path -LiteralPath $pidFile)) { return }
  foreach ($line in Get-Content -LiteralPath $pidFile) {
    $stalePid = 0
    if (-not [int]::TryParse($line.Trim(), [ref]$stalePid)) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $stalePid" -ErrorAction SilentlyContinue
    if ($process -and $process.Name -eq 'node.exe' -and $process.CommandLine -match 'dist[\\/](exit|gateway)\.js') {
      Write-Log "deteniendo instancia previa pid=$stalePid"
      Stop-Process -Id $stalePid -Force -ErrorAction SilentlyContinue
    }
  }
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

function Get-ExpectedTailscaleIps {
  $ips = @()
  $envFile = Join-Path $root '.env'
  if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
      if ($line -match '^\s*(EXIT_HOST|GATEWAY_HOST)\s*=\s*(\S+)') { $ips += $Matches[2] }
    }
  }
  return @($ips | Select-Object -Unique)
}

function Wait-Tailscale {
  $expected = @(Get-ExpectedTailscaleIps)
  if (-not $expected.Count) {
    $tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $tailscale) {
      $ip = & $tailscale ip -4 2>$null | Select-Object -First 1
      if ($ip) { $expected = @($ip.Trim()) }
    }
  }
  if (-not $expected.Count) {
    Write-Log 'sin IP de Tailscale en .env; continuo'
    return
  }
  $deadline = (Get-Date).AddMinutes(3)
  while ((Get-Date) -lt $deadline) {
    $local = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress })
    if ($expected | Where-Object { $local -contains $_ }) {
      Write-Log "Tailscale listo: $($expected -join ',')"
      return
    }
    Start-Sleep -Seconds 3
  }
  Write-Log 'Tailscale no respondio en 3 minutos; continuo igual'
}

function Start-Role([string]$Role) {
  $logFile = Join-Path $logDir ("{0}.log" -f $Role)
  $errFile = Join-Path $logDir ("{0}.err.log" -f $Role)
  foreach ($file in @($logFile, $errFile)) {
    if ((Test-Path -LiteralPath $file) -and (Get-Item -LiteralPath $file).Length -gt 0) {
      Move-Item -LiteralPath $file -Destination ($file -replace '\.log$', '.prev.log') -Force
    }
  }
  $process = Start-Process -FilePath $node -ArgumentList @("dist\$Role.js") `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $logFile -RedirectStandardError $errFile
  Write-Log "iniciado $Role pid=$($process.Id)"
  return $process
}

$node = Find-Node
Ensure-Build
Stop-StaleProcesses
Wait-Tailscale

$roleList = @($Roles.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -in @('exit', 'gateway') })
if (-not $roleList.Count) {
  Write-Log "sin roles validos en '$Roles' (usa exit,gateway)"
  exit 1
}

$state = @{}
foreach ($role in $roleList) {
  $state[$role] = @{
    Process     = $null
    Failures    = 0
    UpSince     = $null
    Unhealthy   = 0
    NextAttempt = Get-Date
    Dead        = $false
  }
}

function Save-PidFile {
  $ids = @()
  foreach ($role in $roleList) {
    $process = $state[$role].Process
    if ($process) {
      try { if (-not $process.HasExited) { $ids += $process.Id } } catch { }
    }
  }
  ($ids -join "`n") | Set-Content -LiteralPath $pidFile
}

function Start-RoleTracked([string]$Role) {
  $process = Start-Role $Role
  $entry = $state[$Role]
  $entry.Process = $process
  $entry.UpSince = Get-Date
  $entry.Unhealthy = 0
  $entry.Dead = $false
  Save-PidFile
}

foreach ($role in $roleList) {
  Start-RoleTracked $role
}

$probeIntervalSeconds = 10
$unhealthyLimit = 3
$healthyResetSeconds = 60
$lastProbe = Get-Date

while ($true) {
  Start-Sleep -Seconds 1
  $now = Get-Date

  foreach ($role in $roleList) {
    $entry = $state[$role]

    if ($entry.Dead) {
      if ($now -ge $entry.NextAttempt) {
        Start-RoleTracked $role
        Write-Log "$role reiniciado tras backoff"
      }
      continue
    }

    $alive = $false
    if ($entry.Process) {
      try { $alive = -not $entry.Process.HasExited } catch { $alive = $false }
    }

    if (-not $alive) {
      $code = 'n/a'
      if ($entry.Process) {
        try { $code = $entry.Process.ExitCode } catch { }
      }
      $entry.Failures = $entry.Failures + 1
      $delay = Get-BackoffDelay $entry.Failures
      $entry.NextAttempt = (Get-Date).AddSeconds($delay)
      $entry.Dead = $true
      $entry.Unhealthy = 0
      Save-PidFile
      Write-Log "$role termino (exit=$code); reintento en $delay s (fallos=$($entry.Failures))"
      continue
    }

    if ($entry.UpSince -and $entry.Failures -ne 0) {
      if (((Get-Date) - $entry.UpSince).TotalSeconds -ge $healthyResetSeconds) {
        Write-Log "$role estable $healthyResetSeconds s; reinicio contador de fallos"
        $entry.Failures = 0
      }
    }

    if (($now - $lastProbe).TotalSeconds -ge $probeIntervalSeconds) {
      $endpoint = Get-RoleEndpoint $role
      if (Test-Port $endpoint.Host $endpoint.Port 3000) {
        if ($entry.Unhealthy -ne 0) { Write-Log "$role responde de nuevo en $($endpoint.Host):$($endpoint.Port)" }
        $entry.Unhealthy = 0
      } else {
        $entry.Unhealthy = $entry.Unhealthy + 1
        Write-Log "$role sin aceptar conexiones en $($endpoint.Host):$($endpoint.Port) (chequeo $($entry.Unhealthy)/$unhealthyLimit)"
        if ($entry.Unhealthy -ge $unhealthyLimit) {
          Write-Log "$role colgado (pid=$($entry.Process.Id)); reinicio forzado"
          Stop-Process -Id $entry.Process.Id -Force -ErrorAction SilentlyContinue
          $entry.Failures = $entry.Failures + 1
          $delay = Get-BackoffDelay $entry.Failures
          $entry.NextAttempt = (Get-Date).AddSeconds($delay)
          $entry.Dead = $true
          $entry.Unhealthy = 0
          Save-PidFile
          Write-Log "$role reintento en $delay s (fallos=$($entry.Failures))"
        }
      }
    }
  }

  $lastProbe = $now
}
