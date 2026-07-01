#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ShrinkBytes = 150GB

function Fail($Message) {
    [Console]::Error.WriteLine($Message)
    exit 1
}

try {
    $secureBoot = Confirm-SecureBootUEFI
} catch {
    Fail 'UEFI firmware is required; Legacy/CSM boot is not supported.'
}

if ($secureBoot) {
    Fail 'Secure Boot must be disabled before using the rEFInd boot path.'
}

$bitLocker = Get-Command Get-BitLockerVolume -ErrorAction SilentlyContinue
if ($bitLocker) {
    $volume = Get-BitLockerVolume -MountPoint 'C:'
    if ($volume.ProtectionStatus -ne 'Off' -or $volume.VolumeStatus -ne 'FullyDecrypted') {
        Fail 'BitLocker must be off and C: fully decrypted before resizing.'
    }
}

$cPartition = Get-Partition -DriveLetter C
$supported = Get-PartitionSupportedSize -DriveLetter C
if (($cPartition.Size - $supported.SizeMin) -lt $ShrinkBytes) {
    Fail 'C: cannot shrink by 150 GiB; move/unpin files or shrink manually first.'
}

Write-Output 'OK'
