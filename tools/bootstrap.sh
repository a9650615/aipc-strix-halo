#!/bin/bash
# Bootstrap a vanilla bazzite-dx host to the aipc image.
# Usage: bash tools/bootstrap.sh
# Re-running with the same target tag is idempotent.
set -eu

err() { printf '%s\n' "$*" >&2; }

# 1. Hardware probe
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
    err "ERROR: RAM ${mem_kb} kB detected; need ≥ 120 GiB (125829120 kB)"
    exit 1
fi

echo "Hardware OK: iGPU present, XDNA present, RAM ${mem_kb} kB"

# 2. Tag
read -rp "Image tag [stable]: " tag
tag="${tag:-stable}"

# 3. GitHub user
read -rp "GitHub username (owner of ghcr.io/<user>/aipc): " github_user
if [ -z "${github_user}" ]; then
    err "ERROR: GitHub username is required"
    exit 1
fi

image="ghcr.io/${github_user}/aipc:${tag}"

# 4. Idempotency: skip switch if target already active or staged
if bootc status 2>/dev/null | grep -qF "${image}"; then
    echo "${image} is already active; nothing to do."
    exit 0
fi

# 5. Age public key
echo "Enter your age public key (age1...) or a path to a file containing it:"
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
echo "Wrote age public key to /etc/aipc/age.pub"

# 6. Switch
echo "Running: sudo bootc switch ${image}"
sudo bootc switch "${image}"

# 7. Reboot
read -rp "Reboot now? [Y/n]: " answer
case "${answer:-Y}" in
    [Yy]*) sudo systemctl reboot ;;
    *)     echo "Skipping reboot. Run 'sudo systemctl reboot' when ready." ;;
esac
