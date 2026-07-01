#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$backend = Join-Path $PSScriptRoot 'targets\windows\install-windows.ps1'

function Show-Journey {
    Write-Host ''
    Write-Host '=== AIPC Windows Installer — Guided Flow ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host 'Install journey:' -ForegroundColor Yellow
    Write-Host '  1. Windows: stage installer (this script)'
    Write-Host '  2. Reboot and test AIPC Bazzite Installer entry (manual)'
    Write-Host '  3. Install Bazzite to remaining free space (manual, Bazzite installer)'
    Write-Host '  4. Boot installed Bazzite and run install-aipc-linux.sh (manual)'
    Write-Host ''
    Write-Host 'What this script does:' -ForegroundColor Yellow
    Write-Host '  - Read-only preflight checks (BitLocker, UEFI, Secure Boot, disk space)'
    Write-Host '  - Verified rEFInd download and install'
    Write-Host '  - Confirmed C: shrink to 150 GiB unallocated'
    Write-Host '  - Confirmed 30 GiB exFAT AIPC_LIVE partition'
    Write-Host '  - Verified Bazzite ISO download and payload staging'
    Write-Host '  - rEFInd menuentry generation'
    Write-Host ''
    Write-Host 'What remains manual:' -ForegroundColor Yellow
    Write-Host '  - BIOS boot selection (AIPC Bazzite Installer entry)'
    Write-Host '  - Bazzite disk selection in installer'
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

function Show-Menu {
    Write-Host ''
    Write-Host '=== Guided Menu ===' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  [1] Show install journey overview'
    Write-Host '  [2] Show basic settings checklist'
    Write-Host '  [3] Run read-only preflight checks'
    Write-Host '  [4] Start staging (destructive, requires confirmation)'
    Write-Host '  [5] Show next steps after staging'
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
            Write-Host 'Starting staging. This will:' -ForegroundColor Yellow
            Write-Host '  - Install rEFInd to EFI System Partition'
            Write-Host '  - Shrink C: to leave 150 GiB unallocated'
            Write-Host '  - Create and format 30 GiB exFAT AIPC_LIVE partition'
            Write-Host '  - Download and stage Bazzite payload'
            Write-Host '  - Generate rEFInd menuentry'
            Write-Host ''
            Write-Host 'Each destructive step will print the exact plan and require typed confirmation.' -ForegroundColor Magenta
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
                Write-Host 'Staging failed. Check the error above.' -ForegroundColor Red
            }
            break
        }
        '5' { Show-NextSteps }
        '0' { exit 0 }
        default { Write-Host 'Invalid choice.' -ForegroundColor Red }
    }
}
