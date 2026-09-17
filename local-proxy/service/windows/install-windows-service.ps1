<#
  Instala local-proxy (gateway y/o exit) como SERVICIO REAL de Windows usando
  WinSW v2.12.0 (Windows Service Wrapper). Es una alternativa OPCIONAL a las
  tareas de Task Scheduler: antes de usarla desinstala/deshabilita las tareas
  viejas para no arrancar los procesos dos veces (ver docs/service.md).

  Debe ejecutarse en una consola ELEVADA (Ejecutar como administrador).

  Uso:
    powershell -ExecutionPolicy Bypass -File service\windows\install-windows-service.ps1
    ... -Role gateway
    ... -Role exit
    ... -Role all

  WinSW es un binario EXTERNO. Se descarga del release oficial v2.12.0 solo si
  falta. WinSW no publica un SHA256 oficial, asi que NO se fija un hash: el script
  valida que el archivo sea un ejecutable PE (cabecera MZ) y no este vacio, y avisa
  del estado de la firma Authenticode. Si tu tienes el hash, pasalo con
  -ExpectedSha256 <HEX> y se verificara.
#>
param(
  [ValidateSet('gateway', 'exit', 'all')]
  [string]$Role = 'all',

  [string]$ExpectedSha256 = '',

  [switch]$SkipDownload
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
  Write-Error $Message
  exit 1
}

# --- 1. Debe correr como administrador ---
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Fail 'Se requiere una consola elevada. Abre PowerShell como Administrador y vuelve a intentarlo.'
}

# --- 2. Rutas y version pinneada de WinSW ---
$scriptDir = $PSScriptRoot
$projectDir = Split-Path -Parent (Split-Path -Parent $scriptDir)
$runtimeDir = Join-Path $scriptDir 'runtime'
$logsDir = Join-Path $projectDir 'logs'

$winswVersion = '2.12.0'
$is64 = [Environment]::Is64BitOperatingSystem
$winswAsset = if ($is64) { 'WinSW-x64.exe' } else { 'WinSW-x86.exe' }
$winswPath = Join-Path $scriptDir $winswAsset
$winswUrl = "https://github.com/winsw/winsw/releases/download/v$winswVersion/$winswAsset"

Write-Output "Proyecto:  $projectDir"
Write-Output "WinSW:     $winswPath ($winswAsset v$winswVersion)"

# --- 3. Resolver node.exe ---
function Resolve-Node {
  $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
  if (-not $cmd) { $cmd = Get-Command node -ErrorAction SilentlyContinue }
  if ($cmd -and $cmd.Source) { return $cmd.Source }
  $candidates = @(
    (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe')
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  return $null
}

$node = Resolve-Node
if (-not $node) { Fail 'No encontre node.exe en PATH ni en las rutas tipicas. Instala Node 22+ y reintenta.' }
Write-Output "Node:      $node"

# --- 4. WinSW: comprobar / descargar / verificar ---
function Test-PeExecutable([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $false }
  $info = Get-Item -LiteralPath $Path
  # 100 KB: descarta respuestas HTML/parciales; WinSW x64/x86 pesan ~17-18 MB.
  if ($info.Length -lt 100KB) { return $false }
  $stream = [System.IO.File]::OpenRead($Path)
  try {
    $b0 = $stream.ReadByte()
    $b1 = $stream.ReadByte()
    return ($b0 -eq 0x4D -and $b1 -eq 0x5A)  # 'MZ'
  } finally {
    $stream.Dispose()
  }
}

if (-not (Test-PeExecutable $winswPath)) {
  if ($SkipDownload) {
    Fail "WinSW no esta en $winswPath y se paso -SkipDownload."
  }
  Write-Output "Descargando WinSW v$winswVersion desde $winswUrl ..."
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $tmp = "$winswPath.download"
  if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
  try {
    Invoke-WebRequest -Uri $winswUrl -OutFile $tmp -UseBasicParsing
  } catch {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    Fail "Fallo la descarga de WinSW: $($_.Exception.Message)"
  }
  if (-not (Test-PeExecutable $tmp)) {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    Fail 'La descarga no parece un ejecutable valido (falta la cabecera MZ o el archivo esta vacio).'
  }
  Move-Item -LiteralPath $tmp -Destination $winswPath -Force
  Write-Output 'WinSW descargado.'
} else {
  Write-Output 'WinSW ya esta presente; no se descarga.'
}

if ($ExpectedSha256) {
  $expected = $ExpectedSha256.Trim().ToUpperInvariant()
  $actual = (Get-FileHash -LiteralPath $winswPath -Algorithm SHA256).Hash
  if ($actual -ne $expected) {
    Fail "SHA256 no coincide. esperado=$expected obtenido=$actual"
  }
  Write-Output "SHA256 verificado: $actual"
} else {
  Write-Output "AVISO: no se verifico SHA256 (WinSW v$winswVersion no publica hash oficial)."
}

try {
  $signature = Get-AuthenticodeSignature -LiteralPath $winswPath
  if ($signature.Status -eq 'Valid') {
    Write-Output "Firma Authenticode valida: $($signature.SignerCertificate.Subject)"
  } else {
    Write-Output "AVISO: la firma Authenticode no es valida (estado=$($signature.Status))."
  }
} catch {
  Write-Output "AVISO: no pude comprobar la firma Authenticode: $($_.Exception.Message)"
}

# --- 5. Generar config e instalar/arrancar el servicio por rol ---
if ($Role -eq 'all') { $roles = @('gateway', 'exit') } else { $roles = @($Role) }

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

foreach ($roleName in $roles) {
  Write-Output "==> $roleName"

  $template = Join-Path $scriptDir "$roleName-service.xml"
  if (-not (Test-Path -LiteralPath $template)) { Fail "no existe la plantilla $template" }

  $distEntry = Join-Path $projectDir "dist\$roleName.js"
  if (-not (Test-Path -LiteralPath $distEntry)) {
    Write-Output "AVISO: falta $distEntry; corre 'npm run build' antes de arrancar el servicio."
  }

  # WinSW exige exe y xml con el mismo nombre base y en el mismo directorio.
  $exe = Join-Path $runtimeDir "$roleName-service.exe"
  Copy-Item -LiteralPath $winswPath -Destination $exe -Force

  $xml = Get-Content -LiteralPath $template -Raw
  $xml = $xml.Replace('{{NODE}}', $node).Replace('{{PROJECT_DIR}}', $projectDir)
  $xmlPath = Join-Path $runtimeDir "$roleName-service.xml"
  Set-Content -LiteralPath $xmlPath -Value $xml -Encoding UTF8

  if ($roleName -eq 'gateway') { $serviceId = 'local-proxy-gateway' } else { $serviceId = 'local-proxy-exit' }

  # Idempotencia: si ya existe, se reinstala con la configuracion nueva.
  if (Get-Service -Name $serviceId -ErrorAction SilentlyContinue) {
    Write-Output "El servicio $serviceId ya existe; reinstalando con la configuracion nueva."
    & $exe stopwait | Out-Null
    & $exe uninstall | Out-Null
    Start-Sleep -Seconds 1
  }

  & $exe install
  if ($LASTEXITCODE -ne 0) { Fail "WinSW 'install' fallo para $roleName (exit=$LASTEXITCODE)" }

  & $exe start
  if ($LASTEXITCODE -ne 0) { Fail "WinSW 'start' fallo para $roleName (exit=$LASTEXITCODE)" }

  Write-Output "OK: servicio '$serviceId' instalado y arrancado."
}

Write-Output ''
Write-Output 'Listo. Estado: Get-Service local-proxy-* | Format-Table Name,Status,StartType'
Write-Output 'Logs:        logs\gateway-service.out.log / .err.log (y exit-service.*)'
Write-Output 'Recuerda: deshabilita el autostart viejo para no arrancar los procesos dos veces.'
