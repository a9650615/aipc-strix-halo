#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$script = Join-Path $PSScriptRoot 'targets\windows\install-windows.ps1'
if (-not (Test-Path $script)) {
    throw "Missing installer script: $script"
}

& $script @args
