#!/usr/bin/env bash
set -eu

cd "$(dirname "${BASH_SOURCE[0]}")"

show_journey() {
    cat <<'EOF'

=== AIPC Linux Bootstrap — Guided Flow ===

Install journey:
  ✓ Windows: stage installer (completed)
  ✓ Reboot and test AIPC Bazzite Installer entry (completed)
  ✓ Install Bazzite to remaining free space (completed)
  → Linux: bootstrap AIPC modules (this script)

What this script does:
  - Probe hardware (AMD Ryzen AI MAX+ 395, ROCm, NPU)
  - Prompt for age key to decrypt secrets
  - Run bootc switch to AIPC image
  - Prompt for reboot

What must already be true:
  - Vanilla Bazzite DX is installed and booted from the internal disk
  - You are NOT running from the live installer
  - Network is available for bootc pull

EOF
}

show_preconditions() {
    cat <<'EOF'

=== Preconditions Checklist ===

Before running bootstrap, confirm:
  [ ] Vanilla Bazzite DX is installed (not live session)
  [ ] Booted from internal disk (not USB/live media)
  [ ] Network is available
  [ ] Age private key is available (for secrets decryption)
  [ ] You have sudo access

The bootstrap will:
  - Probe hardware and report status
  - Ask for age key path
  - Run bootc switch (downloads ~15 GiB)
  - Prompt for reboot

EOF
}

require_acknowledgement() {
    cat <<'EOF'

IMPORTANT: This script must run on the INSTALLED Bazzite system,
not the live installer session.

If you are currently in the Bazzite live installer, exit this script
and complete the installation first.

EOF
    read -rp "Type 'installed' to confirm you are on the installed system: " answer
    if [ "$answer" != "installed" ]; then
        echo "Bootstrap cancelled."
        exit 1
    fi
}

show_menu() {
    cat <<'EOF'

=== Guided Menu ===

  [1] Show install journey overview
  [2] Show preconditions checklist
  [3] Start bootstrap (requires acknowledgement)
  [0] Exit

EOF
}

show_journey
show_preconditions

while true; do
    show_menu
    read -rp "Choose an option: " choice

    case "$choice" in
        1)
            show_journey
            ;;
        2)
            show_preconditions
            ;;
        3)
            require_acknowledgement
            echo ""
            echo "Invoking tools/bootstrap.sh..."
            echo ""
            exec bash tools/bootstrap.sh "$@"
            ;;
        0)
            exit 0
            ;;
        *)
            echo "Invalid choice." >&2
            ;;
    esac
done
