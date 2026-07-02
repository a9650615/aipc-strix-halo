#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$WorkDir = "$env:ProgramData\aipc-windows-installer",
    [string]$RefIndVersion = '0.14.0',
    [string]$RefIndSha256 = '1ae1eeea8162096eccf8553cd82ecd810dba64bf4ea9cf316d6ce5855e6e2880',
    [string]$BazziteIsoUrl = 'https://download.bazzite.gg/bazzite-stable-amd64.iso',
    [string]$BazziteChecksumUrl = 'https://download.bazzite.gg/bazzite-stable-amd64.iso-CHECKSUM'
)

$ErrorActionPreference = 'Stop'
$script:Cmdlet = $PSCmdlet
$ShrinkBytes = 150GB
$LiveBytes = 30GB
$RefIndZip = Join-Path $WorkDir "refind-bin-$RefIndVersion.zip"
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
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -UserAgent 'Mozilla/5.0' -MaximumRedirection 10
}

function Assert-Checksum($File, $ChecksumFile) {
    $hash = (Get-FileHash -Algorithm SHA256 $File).Hash.ToLowerInvariant()
    $checksums = (Get-Content -Raw $ChecksumFile).ToLowerInvariant()
    if (-not $checksums.Contains($hash)) {
        throw "SHA-256 mismatch for $File"
    }
    Write-Log "  checksum OK: $(Split-Path $File -Leaf)" Green
}

function Assert-Sha256($File, $Expected) {
    $hash = (Get-FileHash -Algorithm SHA256 $File).Hash.ToLowerInvariant()
    if ($hash -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $File (got $hash, expected $Expected)"
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

    # SourceForge's /files/.../download URLs serve an HTML interstitial, not the
    # binary; only the *.dl.sourceforge.net mirrors return the real file. rEFInd
    # publishes no per-file checksum, so the zip hash is pinned to the release.
    $url = "https://master.dl.sourceforge.net/project/refind/$RefIndVersion/refind-bin-$RefIndVersion.zip?viasf=1"
    Save-Download $url $RefIndZip
    Assert-Sha256 $RefIndZip $RefIndSha256

    $extractDir = Join-Path $WorkDir 'refind'
    if (-not (Test-Path $extractDir)) {
        Expand-Archive -Path $RefIndZip -DestinationPath $extractDir
    }
    # The rEFInd binary zip ships no Windows installer; install manually per the
    # rEFInd docs: copy the refind/ payload to the ESP, seed refind.conf, then
    # point the Windows Boot Manager at refind_x64.efi.
    $refindSrc = Get-ChildItem $extractDir -Recurse -Directory -Filter 'refind' |
                 Where-Object { Test-Path (Join-Path $_.FullName 'refind_x64.efi') } |
                 Select-Object -First 1
    if (-not $refindSrc) { throw 'refind_x64.efi not found after extraction.' }

    Invoke-Confirmed 'EFI System Partition / Windows Boot Manager' 'install rEFInd' {
        Copy-Item $refindSrc.FullName $refindDir -Recurse -Force
        $confSample = Join-Path $refindDir 'refind.conf-sample'
        $conf = Join-Path $refindDir 'refind.conf'
        if ((Test-Path $confSample) -and -not (Test-Path $conf)) {
            Copy-Item $confSample $conf
        }
        & bcdedit /set '{bootmgr}' path \EFI\refind\refind_x64.efi | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'bcdedit failed to set the rEFInd boot path.' }
    }
    Complete-Phase 'refind'
}

function Ensure-FreeSpace {
    Set-Phase 'shrink'
    $disk = Get-Disk -Number (Get-SystemDiskNumber)
    # An already-created AIPC_LIVE partition counts toward the 150 GiB target:
    # it was carved out of the space this phase reserved, so on a re-run it is
    # no longer "unallocated" but is still ours. Without this, every idempotent
    # re-run after partition creation would see 30 GiB "missing" and shrink
    # C: again, forever.
    $existingLive = Get-Volume -FileSystemLabel 'AIPC_LIVE' -ErrorAction SilentlyContinue
    $reserved = $disk.LargestFreeExtent
    if ($existingLive) { $reserved += $existingLive.Size }
    # Partition alignment and FAT32 reserved sectors mean a "30 GiB" partition
    # is never byte-exact, so allow slack rather than re-prompting to shrink
    # by a few stray MiB every idempotent re-run.
    $needed = $ShrinkBytes - $reserved - 1GB
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
        if ($volume.FileSystem -ne 'FAT32') { throw 'AIPC_LIVE exists but is not FAT32; delete it in Disk Management and retry.' }
        Write-Log "  AIPC_LIVE already exists at $($volume.DriveLetter):" DarkGray
        Complete-Phase 'partition'
        return "$($volume.DriveLetter):"
    }

    # FAT32 (not exFAT): the Bazzite installer initrd mounts this partition via
    # inst.stage2=hd:LABEL=AIPC_LIVE and reliably reads vfat; the largest file in
    # the installer tree (images/install.img) is < 4 GiB, so FAT32 suffices.
    $diskNumber = Get-SystemDiskNumber
    Invoke-Confirmed "Disk $diskNumber" 'create and format 30 GiB AIPC_LIVE FAT32 partition' {
        $partition = New-Partition -DiskNumber $diskNumber -Size $LiveBytes -AssignDriveLetter
        Format-Volume -Partition $partition -FileSystem FAT32 -NewFileSystemLabel 'AIPC_LIVE' -Confirm:$false | Out-Null
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

function Ensure-Payload($LiveDrive) {
    Set-Phase 'payload'
    Ensure-BazziteIso

    $image = Mount-DiskImage -ImagePath $BazziteIso -PassThru
    try {
        $isoDrive = "$(($image | Get-Volume).DriveLetter):"
        # Bazzite ships an Anaconda installer ISO (images/install.img), not a
        # dracut live ISO (LiveOS/squashfs.img). Mirror the whole tree onto
        # AIPC_LIVE so inst.stage2=hd:LABEL=AIPC_LIVE finds install.img, the
        # OCI repo, and .treeinfo — exactly what a dd-written USB would hold.
        # vmlinuz/initrd stay under images/pxeboot/ on AIPC_LIVE too: the ESP
        # on this hardware is only ~256 MiB (168 MiB free), far too small for
        # the ~242 MiB initrd, so rEFInd loads them straight off AIPC_LIVE via
        # a "volume" directive instead of staging a copy onto the ESP.
        $marker = Join-Path $LiveDrive 'images\install.img'
        if (-not (Test-Path $marker)) {
            Write-Log '  copying installer tree to AIPC_LIVE...'
            Copy-Item "$isoDrive\*" "$LiveDrive\" -Recurse -Force
        } else {
            Write-Log '  installer tree already staged' DarkGray
        }
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

    # loader/initrd are read from the AIPC_LIVE volume (not the ESP) via the
    # "volume" directive; rEFInd reads FAT natively, no driver needed.
    $entry = @'

menuentry "AIPC Bazzite Installer (UNVERIFIED on Strix Halo)" {
    icon /EFI/refind/icons/os_linux.png
    volume "AIPC_LIVE"
    loader /images/pxeboot/vmlinuz
    initrd /images/pxeboot/initrd.img
    options "inst.stage2=hd:LABEL=AIPC_LIVE quiet"
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
        Ensure-Payload $liveDrive
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
