#!/usr/bin/env bash
set -eu

cd "$(dirname "${BASH_SOURCE[0]}")"

show_journey() {
    cat <<'EOF'

=== AIPC Linux Bootstrap - Guided Flow ===

Install journey:
  [done] Windows: stage installer
  [done] Reboot and test AIPC Bazzite Installer entry
  [done] Install Bazzite to remaining free space
  [HERE] Linux: bootstrap AIPC modules (this script)

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

Recovery if bootstrap fails:
  - Log file: /var/log/aipc-bootstrap.log
  - Each phase is idempotent; safe to retry
  - bootc switch can be re-run without side effects
  - If stuck: journalctl -u bootc-fetch-apply-updates

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
  [4] Show recovery/debug info
  [0] Exit

EOF
}

show_recovery() {
    cat <<'EOF'

=== Recovery & Debug Info ===

Log file: /var/log/aipc-bootstrap.log
  (created on first run, contains all phase output)

Diagnostic commands:
  lspci | grep -iE 'gfx1151|Radeon|xdna'    # hardware check
  free -h                                    # RAM check
  sudo bootc status                          # current image status
  journalctl -u bootc-fetch-apply-updates    # bootc update logs
  cat /etc/aipc/age.pub                      # age key check

Recovery paths:
  hardware-probe failed  -> verify machine is Strix Halo (lspci, free -h)
  age-key failed         -> re-run bootstrap, paste correct age1... key
  bootc-switch failed    -> check network, retry; bootc status shows state
  reboot declined        -> run: sudo systemctl reboot

After successful bootstrap:
  1. Reboot
  2. Run: aipc doctor
  3. Wait for 30 days of green before wiping Windows

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
        4)
            show_recovery
            ;;
        0)
            exit 0
            ;;
        *)
            echo "Invalid choice." >&2
            ;;
    esac
done
