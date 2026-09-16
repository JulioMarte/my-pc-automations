param(
  [string]$TaskName = 'local-proxy-autostart',
  [string]$WatchdogName = 'local-proxy-watchdog'
)

$ErrorActionPreference = 'Continue'

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $WatchdogName -Confirm:$false -ErrorAction SilentlyContinue

# procesos listados en el pid file
$pidFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\autostart.pids'
if (Test-Path -LiteralPath $pidFile) {
  foreach ($line in Get-Content -LiteralPath $pidFile) {
    $processId = 0
    if (-not [int]::TryParse($line.Trim(), [ref]$processId)) { continue }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'node') {
      Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
  }
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

# procesos sueltos que corren dist\exit.js / dist\gateway.js
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'dist[\\/](exit|gateway)\.js' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Output "Tarea '$TaskName' eliminada y procesos del autostart detenidos."
