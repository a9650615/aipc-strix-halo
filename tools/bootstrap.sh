#!/bin/bash
# Bootstrap a vanilla bazzite-dx host to the aipc image.
# Usage: bash tools/bootstrap.sh
# Re-running with the same target tag is idempotent.
set -eu

LOGFILE="/var/log/aipc-bootstrap.log"
PHASES_DONE=()
PHASE_FAILED=""

log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] $*" | sudo tee -a "$LOGFILE" > /dev/null 2>&1 || true
    echo "[$ts] $*"
}

set_phase() {
    log ">>> Phase: $1"
    PHASE_FAILED="$1"
}

complete_phase() {
    PHASES_DONE+=("$1")
    log "    $1 done"
}

err() { printf '%s\n' "$*" >&2; log "ERROR: $*" ; }

show_failure_summary() {
    echo ''
    echo '=== BOOTSTRAP FAILED ==='
    echo ''
    echo "Error: $*"
    echo ''
    echo "Failed at phase: $PHASE_FAILED"
    echo ''
    echo 'Phases completed:'
    if [ "${#PHASES_DONE[@]}" -eq 0 ]; then
        echo '  (none)'
    else
        for p in "${PHASES_DONE[@]}"; do echo "  [ok] $p"; done
    fi
    echo ''
    echo 'Recovery hints:'
    case "$PHASE_FAILED" in
        hardware-probe)
            echo '  This machine may not be Strix Halo. Check:'
            echo '    lspci | grep -iE "gfx1151|Radeon 8060|xdna"'
            echo '    free -h'
            echo '  No changes were made. Safe to retry after fixing hardware.'
            ;;
        age-key)
            echo '  Age key setup failed. Check:'
            echo '    cat /etc/aipc/age.pub'
            echo '  Ensure your age public key starts with "age1".'
            echo '  Safe to retry: no disk changes were made.'
            ;;
        bootc-switch)
            echo '  bootc switch failed. Check:'
            echo '    sudo bootc status'
            echo '    podman pull <image>'
            echo '  Network required. Retry after ensuring connectivity.'
            ;;
        reboot)
            echo '  Switch completed but reboot was declined.'
            echo '  Run: sudo systemctl reboot'
            echo '  After reboot, run: aipc doctor'
            ;;
        *)
            echo '  Check the log file for details: '"$LOGFILE"
            echo '  Retry from the guided menu.'
            ;;
    esac
    echo ''
    echo "Full log: $LOGFILE"
    echo ''
    echo 'Safe next steps:'
    echo '  1. Fix the issue above, then retry bootstrap.'
    echo '  2. After successful bootstrap + reboot, run: aipc doctor'
    echo '  3. If stuck, check: journalctl -u bootc-fetch-apply-updates'
}

trap 'show_failure_summary "Bootstrap failed at phase: $PHASE_FAILED"' ERR

sudo mkdir -p "$(dirname "$LOGFILE")"
log "=== AIPC Bootstrap ==="
log "Log: $LOGFILE"

# 1. Hardware probe
set_phase "hardware-probe"

if ! lspci | grep -qiE 'gfx1151|Radeon 8060'; then
    err "ERROR: Strix Halo iGPU (gfx1151 / Radeon 8060) not detected via lspci"
    exit 1
fi

if ! lspci | grep -qiE 'xdna|Signal Processing'; then
    err "ERROR: XDNA NPU not detected via lspci"
    exit 1
fi

mem_kb=$(awk '/^MemTotal:/{print $2}' /proc/meminfo)
# 120 GiB = 125829120 kB
if [ "${mem_kb}" -lt 125829120 ]; then
    err "ERROR: RAM ${mem_kb} kB detected; need >= 120 GiB (125829120 kB)"
    exit 1
fi

log "Hardware OK: iGPU present, XDNA present, RAM ${mem_kb} kB"
complete_phase "hardware-probe"

# 2. Tag
set_phase "tag"
read -rp "Image tag [stable]: " tag
tag="${tag:-stable}"
complete_phase "tag"

# 3. GitHub user
set_phase "github-user"
read -rp "GitHub username (owner of ghcr.io/<user>/aipc): " github_user
if [ -z "${github_user}" ]; then
    err "ERROR: GitHub username is required"
    exit 1
fi

image="ghcr.io/${github_user}/aipc:${tag}"
complete_phase "github-user"

# 4. Idempotency: skip switch if target already active or staged
set_phase "idempotency-check"
if bootc status 2>/dev/null | grep -qF "${image}"; then
    log "${image} is already active; nothing to do."
    complete_phase "idempotency-check"
    exit 0
fi
complete_phase "idempotency-check"

# 5. Age public key
set_phase "age-key"
log "Enter your age public key (age1...) or a path to a file containing it:"
read -rp "> " age_input
if [ -z "${age_input}" ]; then
    err "ERROR: age public key is required"
    exit 1
fi

if [ -f "${age_input}" ]; then
    age_pub=$(cat "${age_input}")
else
    age_pub="${age_input}"
fi

case "${age_pub}" in
    age1*) ;;
    *) err "ERROR: expected key starting with 'age1', got: ${age_pub}"; exit 1 ;;
esac

sudo mkdir -p /etc/aipc
printf '%s\n' "${age_pub}" | sudo tee /etc/aipc/age.pub > /dev/null
sudo chmod 644 /etc/aipc/age.pub
log "Wrote age public key to /etc/aipc/age.pub"
complete_phase "age-key"

# 6. Switch
set_phase "bootc-switch"
log "Running: sudo bootc switch ${image}"
sudo bootc switch "${image}"
complete_phase "bootc-switch"

# 7. Reboot
set_phase "reboot"
log "Bootstrap complete. Image switched to ${image}."
log ''
log '=== BOOTSTRAP SUCCESSFUL ==='
log ''
log 'Phases completed:'
for p in "${PHASES_DONE[@]}"; do log "  [ok] $p"; done
log ''
log 'Next steps:'
log '  1. Reboot now to apply the new image.'
log '  2. After reboot, run: aipc doctor'
log '  3. Wait for aipc doctor to stay green for 30 days.'
log ''
log "Full log: $LOGFILE"

trap - ERR

read -rp "Reboot now? [Y/n]: " answer
case "${answer:-Y}" in
    [Yy]*) sudo systemctl reboot ;;
    *)     log "Skipping reboot. Run 'sudo systemctl reboot' when ready." ;;
esac
