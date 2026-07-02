#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$backend = Join-Path $PSScriptRoot 'targets\windows\install-windows.ps1'
$BazziteIsoUrl = 'https://download.bazzite.gg/bazzite-stable-amd64.iso'
$BazziteChecksumUrl = 'https://download.bazzite.gg/bazzite-stable-amd64.iso-CHECKSUM'
$WorkDir = "$env:ProgramData\aipc-windows-installer"

function Write-Log($Message, $Color = 'White') {
    Write-Host $Message -ForegroundColor $Color
}

function Confirm-Usb($Prompt) {
    $answer = Read-Host "$Prompt Type yes to continue"
    if ($answer -ne 'yes') { throw 'User declined.' }
}

function Invoke-UsbConfirmed($Target, $Action, [scriptblock]$Block) {
    Write-Log "PLAN: $Action on $Target" Yellow
    Confirm-Usb 'Destructive step on USB SSD.'
    if ($PSCmdlet.ShouldProcess($Target, $Action)) { & $Block }
}

function Assert-UsbChecksum($File, $ChecksumFile) {
    $hash = (Get-FileHash -Algorithm SHA256 $File).Hash.ToLowerInvariant()
    $checksums = (Get-Content -Raw $ChecksumFile).ToLowerInvariant()
    if (-not $checksums.Contains($hash)) {
        throw "SHA-256 mismatch for $File"
    }
    Write-Log "  checksum OK: $(Split-Path $File -Leaf)" Green
}

function Show-Journey {
    Write-Host ''
    Write-Host '=== AIPC Windows Installer - Guided Flow ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'Install paths:' -ForegroundColor Yellow
    Write-Host '  [A] No-USB path (stage installer from Windows, reboot into Bazzite installer)'
    Write-Host '  [B] USB SSD path (create bootable USB SSD, boot from it, install Bazzite)'
    Write-Host ''
    Write-Host 'What remains manual after either path:' -ForegroundColor Yellow
    Write-Host '  - Bazzite disk selection in the installer'
    Write-Host '  - Boot path is UNVERIFIED on Strix Halo hardware'
    Write-Host ''
}

function Show-Settings {
    Write-Host ''
    Write-Host '=== Basic Settings Checklist ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'Before staging, confirm:' -ForegroundColor Yellow
    Write-Host '  [ ] BitLocker is OFF (Settings > Privacy & security > Device encryption)'
    Write-Host '  [ ] Secure Boot is OFF (msinfo32 > Secure Boot State)'
    Write-Host '  [ ] Firmware is UEFI (msinfo32 > BIOS Mode)'
    Write-Host '  [ ] C: can shrink by 150 GiB (preflight check will verify)'
    Write-Host '  [ ] Windows System Image Backup completed on NON-USB storage'
    Write-Host '      (required for WinRE recovery if boot fails)'
    Write-Host ''
    Write-Host 'Windows will NOT be wiped automatically.' -ForegroundColor Magenta
    Write-Host 'Boot path is UNVERIFIED on Strix Halo.' -ForegroundColor Magenta
    Write-Host ''
}

function Run-Preflight {
    Write-Host ''
    Write-Host 'Running read-only preflight checks...' -ForegroundColor Cyan
    Write-Host ''
    $preflight = Join-Path $PSScriptRoot 'targets\windows\preflight-check.ps1'
    if (-not (Test-Path $preflight)) {
        throw "Missing preflight script: $preflight"
    }
    & $preflight
    return $LASTEXITCODE
}

function Show-NextSteps {
    Write-Host ''
    Write-Host '=== Next Steps After Staging ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '1. Reboot the machine.'
    Write-Host '2. In rEFInd menu, choose "AIPC Bazzite Installer (UNVERIFIED on Strix Halo)".'
    Write-Host '3. Test the live environment (keyboard, network, display).'
    Write-Host '4. Run the Bazzite installer and select the REMAINING FREE SPACE only.'
    Write-Host '   Do NOT select the Windows partition or AIPC_LIVE partition.'
    Write-Host '5. After install, boot into installed Bazzite from the internal disk.'
    Write-Host '6. Clone this repo and run: ./install-aipc-linux.sh'
    Write-Host '7. Wait for "aipc doctor" to stay green for 30 days before wiping Windows.'
    Write-Host ''
}

function Select-ExternalDisk {
    Write-Host ''
    Write-Host '=== Select USB SSD for Installer ===' -ForegroundColor Cyan
    Write-Host ''
    $disks = Get-Disk | Where-Object { $_.BusType -eq 'USB' -or $_.BusType -eq 'ATA' } |
             Where-Object { $_.Size -gt 00GB }
    if ($disks.Count -eq 0) {
        Write-Host 'No external disks found.' -ForegroundColor Red
        return $null
    }
    Write-Host 'Available USB/external disks:' -ForegroundColor Yellow
    $i = 1
    foreach ($d in $disks) {
        $sizeGB = [math]::Round($d.Size / 1GB, 1)
        $freeGB = [math]::Round($d.LargestFreeExtent / 1GB, 1)
        Write-Host "  [$i] Disk $($d.Number): $($d.FriendlyName) | Size: ${sizeGB} GiB | Free: ${freeGB} GiB | Bus: $($d.BusType)"
        $i++
    }
    Write-Host ''
    $choice = Read-Host "Choose disk number (1-$($disks.Count))"
    $idx = [int]$choice - 1
    if ($idx -lt 0 -or $idx -ge $disks.Count) {
        Write-Host 'Invalid choice.' -ForegroundColor Red
        return $null
    }
    return $disks[$idx]
}

function Ensure-UsbPartition($Disk) {
    Write-Host ''
    Write-Host "=== Prepare USB SSD Partitions ===" -ForegroundColor Cyan
    Write-Host "Selected: Disk $($Disk.Number) - $($Disk.FriendlyName)"
    Write-Host "Size: $([math]::Round($Disk.Size / 1GB, 1)) GiB | Free: $([math]::Round($Disk.LargestFreeExtent / 1GB, 1)) GiB"
    Write-Host ''
    $espGB = 1
    $liveGB = 35
    $totalGB = $espGB + $liveGB
    if ($Disk.LargestFreeExtent -lt ($totalGB * 1GB)) {
        Write-Host "Not enough free space on USB SSD. Need at least ${totalGB} GiB." -ForegroundColor Red
        Write-Host 'Delete some files or use a different disk.'
        return $null
    }

    $existingLive = Get-Partition -DiskNumber $Disk.Number -ErrorAction SilentlyContinue |
                    Where-Object { $_.FileSystemLabel -eq 'AIPC_LIVE' }
    $existingEsp = Get-Partition -DiskNumber $Disk.Number -ErrorAction SilentlyContinue |
                   Where-Object { $_.Type -eq 'System' }

    if ($existingLive -and $existingEsp) {
        Write-Host '  USB SSD already has ESP + AIPC_LIVE partitions.' -ForegroundColor Yellow
        return @{ EspDrive = "$($existingEsp.DriveLetter):"; LiveDrive = "$($existingLive.DriveLetter):" }
    }

    Write-Host "This will create TWO partitions on the USB SSD:" -ForegroundColor Yellow
    Write-Host "  1. ${espGB} GiB FAT32 ESP (boot files: BOOTX64.EFI, vmlinuz, initrd)"
    Write-Host "  2. ${liveGB} GiB exFAT AIPC_LIVE (LiveOS payload)"
    Write-Host "Existing data on the disk will NOT be affected." -ForegroundColor Yellow
    Write-Host ''
    $confirm = Read-Host "Type 'create' to create partitions on USB SSD"
    if ($confirm -ne 'create') {
        Write-Host 'Cancelled.' -ForegroundColor Yellow
        return $null
    }
    Write-Host ''

    if (-not $existingEsp) {
        Write-Log "  creating ${espGB} GiB FAT32 ESP..."
        Invoke-UsbConfirmed "Disk $($Disk.Number)" "create ${espGB} GiB FAT32 ESP" {
            $espPart = New-Partition -DiskNumber $Disk.Number -Size ($espGB * 1GB) -AssignDriveLetter -GptType '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
            Format-Volume -Partition $espPart -FileSystem FAT32 -NewFileSystemLabel 'AIPC_ESP' -Confirm:$false | Out-Null
        }
    }
    if (-not $existingLive) {
        Write-Log "  creating ${liveGB} GiB exFAT AIPC_LIVE..."
        Invoke-UsbConfirmed "Disk $($Disk.Number)" "create ${liveGB} GiB exFAT AIPC_LIVE partition" {
            $livePart = New-Partition -DiskNumber $Disk.Number -Size ($liveGB * 1GB) -AssignDriveLetter
            Format-Volume -Partition $livePart -FileSystem exFAT -NewFileSystemLabel 'AIPC_LIVE' -Confirm:$false | Out-Null
        }
    }

    $espVol = Get-Volume -FileSystemLabel 'AIPC_ESP'
    $liveVol = Get-Volume -FileSystemLabel 'AIPC_LIVE'
    return @{ EspDrive = "$($espVol.DriveLetter):"; LiveDrive = "$($liveVol.DriveLetter):" }
}

function Stage-UsbPayload($Drives) {
    $EspDrive = $Drives.EspDrive
    $LiveDrive = $Drives.LiveDrive
    Write-Host ''
    Write-Host '=== Stage Bazzite Payload to USB SSD ===' -ForegroundColor Cyan
    Write-Host "ESP: $EspDrive | AIPC_LIVE: $LiveDrive"
    Write-Host ''
    Write-Host "Downloading and verifying Bazzite ISO..."
    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    $iso = Join-Path $WorkDir 'bazzite-stable-amd64.iso'
    $chk = Join-Path $WorkDir 'bazzite-stable-amd64.iso-CHECKSUM'
    if (-not (Test-Path $iso)) {
        Write-Log "  downloading: $BazziteIsoUrl"
        Invoke-WebRequest -Uri $BazziteIsoUrl -OutFile $iso
    }
    if (-not (Test-Path $chk)) {
        Invoke-WebRequest -Uri $BazziteChecksumUrl -OutFile $chk
    }
    Assert-UsbChecksum $iso $chk
    Write-Host ''
    $bootDir = Join-Path $EspDrive 'EFI\BOOT'
    New-Item -ItemType Directory -Force -Path $bootDir | Out-Null
    $liveOs = Join-Path $LiveDrive 'LiveOS'

    $image = Mount-DiskImage -ImagePath $iso -PassThru
    try {
        $isoVolume = $image | Get-Volume
        $isoDrive = "$($isoVolume.DriveLetter):"
        if (-not (Test-Path $liveOs)) {
            Write-Log "  copying LiveOS to AIPC_LIVE..."
            Copy-Item (Join-Path $isoDrive 'LiveOS') $LiveDrive -Recurse -Force
        }
        Write-Log "  copying boot files to ESP..."
        $srcBoot = Join-Path $isoDrive 'EFI\BOOT'
        if (Test-Path $srcBoot) {
            Copy-Item (Join-Path $srcBoot '*') $bootDir -Force
        }
        Write-Log "  extracting vmlinuz + initrd to ESP..."
        $srcVmlinuz = Get-ChildItem $isoDrive -Recurse -Filter 'vmlinuz*' | Select-Object -First 1
        $srcInitrd = Get-ChildItem $isoDrive -Recurse -Filter 'initrd*' | Select-Object -First 1
        if ($srcVmlinuz) { Copy-Item $srcVmlinuz.FullName (Join-Path $bootDir 'vmlinuz') -Force }
        if ($srcInitrd) { Copy-Item $srcInitrd.FullName (Join-Path $bootDir 'initrd.img') -Force }
    } finally {
        Dismount-DiskImage -ImagePath $iso | Out-Null
    }
}

function Run-UsbPath {
    Write-Host ''
    Write-Host '=== USB SSD Installer Path ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'This path creates a bootable USB SSD from an external drive.' -ForegroundColor Yellow
    Write-Host 'Creates: 1 GiB FAT32 ESP + 35 GiB exFAT AIPC_LIVE on the USB SSD.' -ForegroundColor Yellow
    Write-Host ''
    $disk = Select-ExternalDisk
    if (-not $disk) { return }
    $drives = Ensure-UsbPartition $disk
    if (-not $drives) { return }
    Stage-UsbPayload $drives
    Write-Host ''
    Write-Host '=== USB SSD READY ===' -ForegroundColor Green
    Write-Host ''
    Write-Host "ESP: $($drives.EspDrive) | AIPC_LIVE: $($drives.LiveDrive)" -ForegroundColor Green
    Write-Host ''
    Write-Host 'Next steps:' -ForegroundColor Cyan
    Write-Host '  1. Safely eject the USB SSD.'
    Write-Host '  2. Plug it into the target machine.'
    Write-Host '  3. Boot and press F12/F1 for one-time boot menu.'
    Write-Host '  4. Select the USB SSD to boot Bazzite installer.'
    Write-Host '  5. Install Bazzite to the internal disk (NOT the USB SSD).'
    Write-Host '  6. After install, boot installed Bazzite and run: ./install-aipc-linux.sh'
    Write-Host ''
}

function Show-Menu {
    Write-Host ''
    Write-Host '=== Guided Menu ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  [1] Show install journey overview'
    Write-Host '  [2] Show basic settings checklist'
    Write-Host '  [3] Run read-only preflight checks'
    Write-Host '  [4] Start NO-USB staging (internal disk, destructive)'
    Write-Host '  [5] Start USB SSD staging (external disk)'
    Write-Host '  [6] Show next steps after staging'
    Write-Host '  [0] Exit'
    Write-Host ''
}

if (-not (Test-Path $backend)) {
    throw "Missing backend script: $backend"
}

Show-Journey
Show-Settings

while ($true) {
    Show-Menu
    $choice = Read-Host 'Choose an option'

    switch ($choice) {
        '1' { Show-Journey }
        '2' { Show-Settings }
        '3' {
            $code = Run-Preflight
            if ($code -eq 0) {
                Write-Host 'Preflight passed. Safe to proceed with staging.' -ForegroundColor Green
            } else {
                Write-Host 'Preflight failed. Fix the issues above before staging.' -ForegroundColor Red
            }
        }
        '4' {
            Write-Host ''
            Write-Host 'Starting NO-USB staging. This will:' -ForegroundColor Yellow
            Write-Host '  - Install rEFInd to EFI System Partition'
            Write-Host '  - Shrink C: to leave 150 GiB unallocated'
            Write-Host '  - Create and format 30 GiB exFAT AIPC_LIVE partition'
            Write-Host '  - Download and stage Bazzite payload'
            Write-Host '  - Generate rEFInd menuentry'
            Write-Host ''
            Write-Host 'Each destructive step requires typed confirmation.' -ForegroundColor Magenta
            Write-Host ''
            $confirm = Read-Host 'Type "start" to begin staging'
            if ($confirm -ne 'start') {
                Write-Host 'Staging cancelled.' -ForegroundColor Yellow
                continue
            }
            & $backend
            if ($LASTEXITCODE -eq 0) {
                Show-NextSteps
            } else {
                Write-Host 'Staging failed with exit code $LASTEXITCODE. Check log and retry.' -ForegroundColor Red
            }
            break
        }
        '5' {
            Write-Host ''
            Write-Host 'Starting USB SSD staging. This will:' -ForegroundColor Yellow
            Write-Host '  - Let you select an external USB/ATA disk'
            Write-Host '  - Create 1 GiB FAT32 ESP + 35 GiB exFAT AIPC_LIVE on it'
            Write-Host '  - Download and stage Bazzite payload (boot files to ESP, LiveOS to exFAT)'
            Write-Host '  - Make the USB SSD UEFI-bootable'
            Write-Host ''
            Write-Host 'Your existing data on the USB SSD will NOT be affected.' -ForegroundColor Magenta
            Write-Host ''
            $confirm = Read-Host 'Type "usb" to begin USB staging'
            if ($confirm -ne 'usb') {
                Write-Host 'USB staging cancelled.' -ForegroundColor Yellow
                continue
            }
            Run-UsbPath
            break
        }
        '6' { Show-NextSteps }
        '0' { exit 0 }
        default { Write-Host 'Invalid choice.' -ForegroundColor Red }
    }
}
