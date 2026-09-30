# Generated with the reviewed release policy. Windows PowerShell 5.1+, no Python.
param([switch]$DryRun, [string]$Fastboot = 'fastboot')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$work = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
function Invoke-Fastboot([string[]]$Arguments) {
    # Windows PowerShell treats native stderr as errors; fastboot reports there.
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & $Fastboot @Arguments 2>&1; $result = $LASTEXITCODE }
    finally { $ErrorActionPreference = $saved }
    if ($result -ne 0) { throw "fastboot failed ($result): $output" }
    return ($output | Out-String)
}
try {
    $manifest = Get-Content -Raw (Join-Path $PSScriptRoot 'bundle.json') | ConvertFrom-Json
    if ($manifest.device -ne '@DEVICE@' -or $manifest.product -ne '@PRODUCT@' -or $manifest.slot -ne '@SLOT@' -or $manifest.dtbo.ToString().ToLowerInvariant() -ne '@DTBO@') { throw 'Invalid device policy' }
    foreach ($entry in $manifest.sha256.PSObject.Properties) {
        if ($entry.Name -notmatch '^[a-zA-Z0-9._-]+$' -or $entry.Value -notmatch '^[a-f0-9]{64}$') { throw 'Invalid checksum entry' }
        $source = [IO.File]::OpenRead((Join-Path $PSScriptRoot $entry.Name))
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $actual = [BitConverter]::ToString($hasher.ComputeHash($source)).Replace('-', '') }
        finally { $hasher.Dispose(); $source.Dispose() }
        if ($actual -ne $entry.Value) { throw "Checksum mismatch: $($entry.Name)" }
    }
    $required = @('@DEVICE@.img.gz', 'boot.img')
    if ($manifest.dtbo) { $required += 'dtbo.img' }
    foreach ($name in $required) { if ($name -notin $manifest.sha256.PSObject.Properties.Name) { throw "Missing image: $name" } }
    New-Item -ItemType Directory -Path $work | Out-Null
    $rootfs = Join-Path $work 'rootfs.img'
    $source = [IO.File]::OpenRead((Join-Path $PSScriptRoot '@DEVICE@.img.gz'))
    try {
        $gzip = New-Object IO.Compression.GZipStream($source, [IO.Compression.CompressionMode]::Decompress)
        try { $target = [IO.File]::Create($rootfs); try { $gzip.CopyTo($target) } finally { $target.Dispose() } }
        finally { $gzip.Dispose() }
    } finally { $source.Dispose() }
    if ($DryRun) { Write-Output 'Verified @DEVICE@. Would flash userdata, boot_@SLOT@, DTBO=@DTBO@, select @SLOT@ and reboot. No device contacted.'; exit 0 }
    $connected = @((Invoke-Fastboot @('devices')) -split '\r?\n' | Where-Object { $_.Trim() })
    if ($connected.Count -ne 1 -or $connected[0] -notmatch '^(\S+)\s+fastboot\s*$') { throw 'Connect exactly one phone in bootloader fastboot mode' }
    $serial = $Matches[1]
    foreach ($variable in @(@('product', '@PRODUCT@'), @('unlocked', 'yes'))) {
        $output = Invoke-Fastboot @('-s', $serial, 'getvar', $variable[0])
        $pattern = '(?m)^(?:\(bootloader\)\s*)?' + $variable[0] + ':\s*(\S+)'
        if ($output -notmatch $pattern -or $Matches[1] -ne $variable[1]) { throw "Wrong model or locked bootloader: $($variable[0])" }
    }
    Write-Warning 'Experimental image. Replaces the OS and ERASES ALL USER DATA. Back up first.'
    if ((Read-Host 'Type @DEVICE@ to install') -ne '@DEVICE@') { throw 'Cancelled; no writes performed' }
    Invoke-Fastboot @('-s', $serial, 'flash', 'userdata', $rootfs)
    Invoke-Fastboot @('-s', $serial, 'flash', 'boot_@SLOT@', (Join-Path $PSScriptRoot 'boot.img'))
    if ($manifest.dtbo) { Invoke-Fastboot @('-s', $serial, 'flash', 'dtbo_@SLOT@', (Join-Path $PSScriptRoot 'dtbo.img')) }
    Invoke-Fastboot @('-s', $serial, 'set_active', '@SLOT@')
    Invoke-Fastboot @('-s', $serial, 'reboot')
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if (Test-Path $work) { Remove-Item -Recurse -Force $work } }
