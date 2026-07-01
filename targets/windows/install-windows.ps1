#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkDir = "$env:ProgramData\aipc-windows-installer",
    [string]$RefIndVersion = '0.14.0',
    [string]$BazziteIsoUrl = 'https://download.bazzite.gg/bazzite-dx-stable-amd64.iso',
    [string]$BazziteChecksumUrl = 'https://download.bazzite.gg/bazzite-dx-stable-amd64.iso.CHECKSUM'
)

$ErrorActionPreference = 'Stop'
$script:Cmdlet = $PSCmdlet
$ShrinkBytes = 150GB
$LiveBytes = 30GB
$RefIndZip = Join-Path $WorkDir "refind-bin-$RefIndVersion.zip"
$RefIndChecksum = Join-Path $WorkDir "refind-bin-$RefIndVersion.zip.txt"
$BazziteIso = Join-Path $WorkDir 'bazzite-dx-stable-amd64.iso'
$BazziteChecksum = Join-Path $WorkDir 'bazzite-dx-stable-amd64.iso.CHECKSUM'

function Confirm-Yes($Prompt) {
    $answer = Read-Host "$Prompt Type yes to continue"
    if ($answer -ne 'yes') { throw 'User declined.' }
}

function Invoke-Confirmed($Target, $Action, [scriptblock]$Block) {
    Write-Host "PLAN: $Action on $Target"
    Confirm-Yes 'Destructive or boot-changing step.'
    if ($script:Cmdlet.ShouldProcess($Target, $Action)) { & $Block }
}

function Get-FreeDriveLetter {
    foreach ($letter in 'S','T','U','V','W','X','Y','Z') {
        if (-not (Test-Path "$letter`:")) { return "$letter`:" }
    }
    throw 'No free drive letter available for the ESP.'
}

function Mount-Esp {
    $drive = Get-FreeDriveLetter
    mountvol $drive /S | Out-Null
    return $drive
}

function Save-Download($Uri, $OutFile) {
    if (Test-Path $OutFile) { return }
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile
}

function Assert-Checksum($File, $ChecksumFile) {
    $hash = (Get-FileHash -Algorithm SHA256 $File).Hash.ToLowerInvariant()
    $checksums = (Get-Content -Raw $ChecksumFile).ToLowerInvariant()
    if (-not $checksums.Contains($hash)) {
        throw "SHA-256 mismatch for $File"
    }
}

function Get-SystemDiskNumber {
    return (Get-Partition -DriveLetter C).DiskNumber
}

function Ensure-RefInd($Esp) {
    $refindDir = Join-Path $Esp 'EFI\refind'
    $refindEfi = Join-Path $refindDir 'refind_x64.efi'
    if (Test-Path $refindEfi) { return }

    $urlBase = "https://sourceforge.net/projects/refind/files/$RefIndVersion"
    Save-Download "$urlBase/refind-bin-$RefIndVersion.zip/download" $RefIndZip
    Save-Download "$urlBase/refind-bin-$RefIndVersion.zip.txt/download" $RefIndChecksum
    Assert-Checksum $RefIndZip $RefIndChecksum

    $extractDir = Join-Path $WorkDir 'refind'
    if (-not (Test-Path $extractDir)) {
        Expand-Archive -Path $RefIndZip -DestinationPath $extractDir
    }
    $installer = Get-ChildItem $extractDir -Recurse -Filter 'refind-install.bat' | Select-Object -First 1
    if (-not $installer) { throw 'refind-install.bat not found after extraction.' }

    Invoke-Confirmed 'EFI System Partition / NVRAM' 'install rEFInd' {
        Push-Location $installer.DirectoryName
        try { & cmd.exe /c 'refind-install.bat' }
        finally { Pop-Location }
    }
}

function Ensure-FreeSpace {
    $disk = Get-Disk -Number (Get-SystemDiskNumber)
    $needed = $ShrinkBytes - $disk.LargestFreeExtent
    if ($needed -le 0) { return }
    $c = Get-Partition -DriveLetter C
    $targetSize = $c.Size - $needed
    Invoke-Confirmed 'C:' "shrink enough to leave 150 GiB installer space" {
        Resize-Partition -DriveLetter C -Size $targetSize
    }
}

function Ensure-LivePartition {
    $volume = Get-Volume -FileSystemLabel 'AIPC_LIVE' -ErrorAction SilentlyContinue
    if ($volume) {
        if ($volume.FileSystem -ne 'exFAT') { throw 'AIPC_LIVE exists but is not exFAT.' }
        return "$($volume.DriveLetter):"
    }

    $diskNumber = Get-SystemDiskNumber
    Invoke-Confirmed "Disk $diskNumber" 'create and format 30 GiB AIPC_LIVE exFAT partition' {
        $partition = New-Partition -DiskNumber $diskNumber -Size $LiveBytes -AssignDriveLetter
        Format-Volume -Partition $partition -FileSystem exFAT -NewFileSystemLabel 'AIPC_LIVE' -Confirm:$false | Out-Null
    }

    $volume = Get-Volume -FileSystemLabel 'AIPC_LIVE'
    return "$($volume.DriveLetter):"
}

function Ensure-BazziteIso {
    Save-Download $BazziteIsoUrl $BazziteIso
    Save-Download $BazziteChecksumUrl $BazziteChecksum
    Assert-Checksum $BazziteIso $BazziteChecksum
}

function Copy-First($Root, $Filter, $Destination) {
    $source = Get-ChildItem $Root -Recurse -File -Filter $Filter | Select-Object -First 1
    if (-not $source) { throw "$Filter not found in mounted ISO." }
    Copy-Item $source.FullName $Destination -Force
}

function Ensure-Payload($Esp, $LiveDrive) {
    Ensure-BazziteIso
    $aipcDir = Join-Path $Esp 'EFI\refind\aipc'
    New-Item -ItemType Directory -Force -Path $aipcDir | Out-Null
    $liveOs = Join-Path $LiveDrive 'LiveOS'

    $image = Mount-DiskImage -ImagePath $BazziteIso -PassThru
    try {
        $isoVolume = $image | Get-Volume
        $isoDrive = "$($isoVolume.DriveLetter):"
        if (-not (Test-Path $liveOs)) {
            Copy-Item (Join-Path $isoDrive 'LiveOS') $LiveDrive -Recurse -Force
        }
        Copy-First $isoDrive 'vmlinuz*' (Join-Path $aipcDir 'vmlinuz')
        Copy-First $isoDrive 'initrd*' (Join-Path $aipcDir 'initrd.img')
    } finally {
        Dismount-DiskImage -ImagePath $BazziteIso | Out-Null
    }
}

function Ensure-MenuEntry($Esp) {
    $conf = Join-Path $Esp 'EFI\refind\refind.conf'
    if (-not (Test-Path $conf)) { throw 'rEFInd config not found on ESP.' }
    $existing = Get-Content -Raw $conf
    if ($existing.Contains('AIPC Bazzite Installer')) { return }

    $entry = @'

menuentry "AIPC Bazzite Installer (UNVERIFIED on Strix Halo)" {
    icon /EFI/refind/icons/os_linux.png
    loader /EFI/refind/aipc/vmlinuz
    initrd /EFI/refind/aipc/initrd.img
    options "root=live:LABEL=AIPC_LIVE rd.live.image quiet"
}
'@
    Add-Content -Path $conf -Value $entry
}

& (Join-Path $PSScriptRoot 'preflight-check.ps1') | Write-Output
Confirm-Yes 'Confirm you have a completed Windows System Image Backup on non-USB storage for WinRE recovery.'
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$esp = Mount-Esp
try {
    Ensure-RefInd $esp
    Ensure-FreeSpace
    $liveDrive = Ensure-LivePartition
    Ensure-Payload $esp $liveDrive
    Ensure-MenuEntry $esp
} finally {
    mountvol $esp /D | Out-Null
}

Write-Host 'Staging complete. This boot path is UNVERIFIED on Strix Halo.'
Write-Host 'Next: reboot, choose the AIPC Bazzite Installer entry once, then install to the remaining free space only.'
Write-Host 'Do not wipe Windows until aipc doctor has stayed green for at least 30 days.'
