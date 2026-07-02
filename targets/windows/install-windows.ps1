#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkDir = "$env:ProgramData\aipc-windows-installer",
    [string]$RefIndVersion = '0.14.0',
    [string]$BazziteIsoUrl = 'https://download.bazzite.gg/bazzite-stable-amd64.iso',
    [string]$BazziteChecksumUrl = 'https://download.bazzite.gg/bazzite-stable-amd64.iso-CHECKSUM'
)

$ErrorActionPreference = 'Stop'
$script:Cmdlet = $PSCmdlet
$ShrinkBytes = 150GB
$LiveBytes = 30GB
$RefIndZip = Join-Path $WorkDir "refind-bin-$RefIndVersion.zip"
$RefIndChecksum = Join-Path $WorkDir "refind-bin-$RefIndVersion.zip.txt"
$BazziteIso = Join-Path $WorkDir 'bazzite-stable-amd64.iso'
$BazziteChecksum = Join-Path $WorkDir 'bazzite-stable-amd64.iso-CHECKSUM'

$script:LogFile = $null
$script:PhasesDone = @()
$script:PhaseFailed = $null

function Write-Log($Message, $Color = 'White') {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] $Message"
    if ($script:LogFile) { Add-Content $script:LogFile $line }
    Write-Host $line -ForegroundColor $Color
}

function Set-Phase($Name) {
    Write-Log ">>> Phase: $Name" Cyan
}

function Complete-Phase($Name) {
    $script:PhasesDone += $Name
    Write-Log "    $Name done" Green
}

function Show-FailureSummary($ErrMsg) {
    Write-Host ''
    Write-Host '=== INSTALLATION FAILED ===' -ForegroundColor Red
    Write-Host ''
    Write-Log "Error: $ErrMsg" Red
    Write-Host ''
    Write-Host "Failed at phase: $($script:PhaseFailed)" -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'Phases completed:' -ForegroundColor Cyan
    if ($script:PhasesDone.Count -eq 0) {
        Write-Host '  (none)'
    } else {
        foreach ($p in $script:PhasesDone) { Write-Host "  [ok] $p" -ForegroundColor Green }
    }
    Write-Host ''
    Write-Host 'Recovery hints:' -ForegroundColor Cyan
    switch ($script:PhaseFailed) {
        'preflight' {
            Write-Host '  Fix the preflight issues above and retry.'
            Write-Host '  No disk changes were made.'
        }
        'refind' {
            Write-Host '  rEFInd install failed. Check NVRAM space and Secure Boot status.'
            Write-Host '  Retry is safe: downloaded files are cached in WorkDir.'
        }
        'shrink' {
            Write-Host '  C: shrink failed. Check Disk Management for unmovable files.'
            Write-Host '  Run: defrag C: /O then retry. No partitions were created.'
        }
        'partition' {
            Write-Host '  Partition creation failed. Check Disk Management for existing AIPC_LIVE.'
            Write-Host '  If partial: use Disk Management to delete AIPC_LIVE partition before retry.'
        }
        'payload' {
            Write-Host '  Payload staging failed. Check disk space on AIPC_LIVE and ESP.'
            Write-Host '  ISO download is cached; retry skips re-download if checksum matches.'
        }
        'menuentry' {
            Write-Host '  rEFInd menuentry failed. Check ESP is mounted and refind.conf exists.'
            Write-Host '  Payload is staged; manual menuentry edit may recover this.'
        }
        default {
            Write-Host '  Check the log file for details. Retry from the guided menu.'
        }
    }
    Write-Host ''
    if ($script:LogFile) {
        Write-Host "Full log: $($script:LogFile)" -ForegroundColor Cyan
    }
    Write-Host ''
    Write-Host 'Safe next steps:' -ForegroundColor Cyan
    Write-Host '  1. Fix the issue above, then retry staging from the guided menu.'
    Write-Host '  2. If stuck, run: targets/windows/preflight-check.ps1'
    Write-Host '  3. To recover Windows boot: WinRE > System Image Recovery'
}

function Confirm-Yes($Prompt) {
    $answer = Read-Host "$Prompt Type yes to continue"
    if ($answer -ne 'yes') { throw 'User declined.' }
}

function Invoke-Confirmed($Target, $Action, [scriptblock]$Block) {
    Write-Log "PLAN: $Action on $Target" Yellow
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
    if (Test-Path $OutFile) {
        Write-Log "  cached: $OutFile" DarkGray
        return
    }
    Write-Log "  downloading: $Uri"
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile
}

function Assert-Checksum($File, $ChecksumFile) {
    $hash = (Get-FileHash -Algorithm SHA256 $File).Hash.ToLowerInvariant()
    $checksums = (Get-Content -Raw $ChecksumFile).ToLowerInvariant()
    if (-not $checksums.Contains($hash)) {
        throw "SHA-256 mismatch for $File"
    }
    Write-Log "  checksum OK: $(Split-Path $File -Leaf)" Green
}

function Get-SystemDiskNumber {
    return (Get-Partition -DriveLetter C).DiskNumber
}

function Ensure-RefInd($Esp) {
    Set-Phase 'refind'
    $refindDir = Join-Path $Esp 'EFI\refind'
    $refindEfi = Join-Path $refindDir 'refind_x64.efi'
    if (Test-Path $refindEfi) {
        Write-Log '  rEFInd already installed' DarkGray
        Complete-Phase 'refind'
        return
    }

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
    Complete-Phase 'refind'
}

function Ensure-FreeSpace {
    Set-Phase 'shrink'
    $disk = Get-Disk -Number (Get-SystemDiskNumber)
    $needed = $ShrinkBytes - $disk.LargestFreeExtent
    if ($needed -le 0) {
        Write-Log '  enough free space already' DarkGray
        Complete-Phase 'shrink'
        return
    }
    $c = Get-Partition -DriveLetter C
    $targetSize = $c.Size - $needed
    Invoke-Confirmed 'C:' "shrink to leave 150 GiB installer space" {
        Resize-Partition -DriveLetter C -Size $targetSize
    }
    Complete-Phase 'shrink'
}

function Ensure-LivePartition {
    Set-Phase 'partition'
    $volume = Get-Volume -FileSystemLabel 'AIPC_LIVE' -ErrorAction SilentlyContinue
    if ($volume) {
        if ($volume.FileSystem -ne 'exFAT') { throw 'AIPC_LIVE exists but is not exFAT.' }
        Write-Log "  AIPC_LIVE already exists at $($volume.DriveLetter):" DarkGray
        Complete-Phase 'partition'
        return "$($volume.DriveLetter):"
    }

    $diskNumber = Get-SystemDiskNumber
    Invoke-Confirmed "Disk $diskNumber" 'create and format 30 GiB AIPC_LIVE exFAT partition' {
        $partition = New-Partition -DiskNumber $diskNumber -Size $LiveBytes -AssignDriveLetter
        Format-Volume -Partition $partition -FileSystem exFAT -NewFileSystemLabel 'AIPC_LIVE' -Confirm:$false | Out-Null
    }

    $volume = Get-Volume -FileSystemLabel 'AIPC_LIVE'
    Complete-Phase 'partition'
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
    Set-Phase 'payload'
    Ensure-BazziteIso
    $aipcDir = Join-Path $Esp 'EFI\refind\aipc'
    New-Item -ItemType Directory -Force -Path $aipcDir | Out-Null
    $liveOs = Join-Path $LiveDrive 'LiveOS'

    $image = Mount-DiskImage -ImagePath $BazziteIso -PassThru
    try {
        $isoVolume = $image | Get-Volume
        $isoDrive = "$($isoVolume.DriveLetter):"
        if (-not (Test-Path $liveOs)) {
            Write-Log '  copying LiveOS to AIPC_LIVE...'
            Copy-Item (Join-Path $isoDrive 'LiveOS') $LiveDrive -Recurse -Force
        } else {
            Write-Log '  LiveOS already staged' DarkGray
        }
        Copy-First $isoDrive 'vmlinuz*' (Join-Path $aipcDir 'vmlinuz')
        Copy-First $isoDrive 'initrd*' (Join-Path $aipcDir 'initrd.img')
    } finally {
        Dismount-DiskImage -ImagePath $BazziteIso | Out-Null
    }
    Complete-Phase 'payload'
}

function Ensure-MenuEntry($Esp) {
    Set-Phase 'menuentry'
    $conf = Join-Path $Esp 'EFI\refind\refind.conf'
    if (-not (Test-Path $conf)) { throw 'rEFInd config not found on ESP.' }
    $existing = Get-Content -Raw $conf
    if ($existing.Contains('AIPC Bazzite Installer')) {
        Write-Log '  menuentry already exists' DarkGray
        Complete-Phase 'menuentry'
        return
    }

    $entry = @'

menuentry "AIPC Bazzite Installer (UNVERIFIED on Strix Halo)" {
    icon /EFI/refind/icons/os_linux.png
    loader /EFI/refind/aipc/vmlinuz
    initrd /EFI/refind/aipc/initrd.img
    options "root=live:LABEL=AIPC_LIVE rd.live.image quiet"
}
'@
    Add-Content -Path $conf -Value $entry
    Complete-Phase 'menuentry'
}

try {
    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    $script:LogFile = Join-Path $WorkDir 'install.log'
    Write-Log "=== AIPC Windows Installer ===" Cyan
    Write-Log "WorkDir: $WorkDir"
    Write-Log "Log: $($script:LogFile)"

    Set-Phase 'preflight'
    $preflight = Join-Path $PSScriptRoot 'preflight-check.ps1'
    $preflightOutput = & $preflight 2>&1
    $preflightOutput | ForEach-Object { Write-Log "  $_" }
    if ($LASTEXITCODE -ne 0) {
        $script:PhaseFailed = 'preflight'
        throw "Preflight failed. See output above."
    }
    Complete-Phase 'preflight'

    Confirm-Yes 'Confirm you have a completed Windows System Image Backup on non-USB storage for WinRE recovery.'

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

    Write-Host ''
    Write-Log '=== STAGING COMPLETE ===' Green
    Write-Host ''
    Write-Host 'Phases completed:' -ForegroundColor Green
    foreach ($p in $script:PhasesDone) { Write-Host "  [ok] $p" -ForegroundColor Green }
    Write-Host ''
    Write-Host 'This boot path is UNVERIFIED on Strix Halo.' -ForegroundColor Yellow
    Write-Host 'Next: reboot, choose the AIPC Bazzite Installer entry once, then install to the remaining free space only.'
    Write-Host 'Do not wipe Windows until aipc doctor has stayed green for at least 30 days.'
    Write-Host ''
    Write-Host "Log file: $($script:LogFile)" -ForegroundColor DarkGray

} catch {
    if (-not $script:PhaseFailed) { $script:PhaseFailed = 'unknown' }
    Show-FailureSummary $_.Exception.Message
    exit 1
}
