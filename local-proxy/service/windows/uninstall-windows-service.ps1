<#
  Detiene y desinstala los servicios reales de Windows de local-proxy (WinSW).
  Requiere una consola ELEVADA (Administrador).

  Uso:
    powershell -ExecutionPolicy Bypass -File service\windows\uninstall-windows-service.ps1
    ... -Role gateway
    ... -Role exit
    ... -Role all

  No borra logs ni archivos del proyecto: solo quita el registro del servicio.
#>
param(
  [ValidateSet('gateway', 'exit', 'all')]
  [string]$Role = 'all'
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
  Write-Error $Message
  exit 1
}

# --- Debe correr como administrador ---
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Fail 'Se requiere una consola elevada. Abre PowerShell como Administrador y vuelve a intentarlo.'
}

$scriptDir = $PSScriptRoot
$runtimeDir = Join-Path $scriptDir 'runtime'

if ($Role -eq 'all') { $roles = @('gateway', 'exit') } else { $roles = @($Role) }

foreach ($roleName in $roles) {
  if ($roleName -eq 'gateway') { $serviceId = 'local-proxy-gateway' } else { $serviceId = 'local-proxy-exit' }
  Write-Output "==> $roleName ($serviceId)"

  $exe = Join-Path $runtimeDir "$roleName-service.exe"
  if (Test-Path -LiteralPath $exe) {
    # stopwait espera a que el proceso termine de verdad (drenado).
    & $exe stopwait | Out-Null
    & $exe uninstall | Out-Null
  } elseif (Get-Service -Name $serviceId -ErrorAction SilentlyContinue) {
    # Sin el exe de WinSW, usamos sc.exe como respaldo.
    Write-Output "WinSW no esta en runtime; uso sc.exe para $serviceId."
    & sc.exe stop $serviceId | Out-Null
    & sc.exe delete $serviceId | Out-Null
  } else {
    Write-Output "El servicio $serviceId no esta instalado."
    continue
  }

  if (Get-Service -Name $serviceId -ErrorAction SilentlyContinue) {
    Write-Output "AVISO: el servicio $serviceId sigue registrado; revisalo manualmente."
  } else {
    Write-Output "OK: servicio $serviceId desinstalado."
  }
}

Write-Output ''
Write-Output 'Los logs y el directorio service\windows\runtime\ se conservan (no se borran datos).'
