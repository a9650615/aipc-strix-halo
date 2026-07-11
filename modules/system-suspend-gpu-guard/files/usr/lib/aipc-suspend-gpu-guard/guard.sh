#!/bin/bash
# Block suspend only for *sustained* amdgpu load on AC.
# Ambient desktop + always-on local models often sit at 10–30% busy on this
# box; a raw 15% threshold never releases the sleep inhibitor ("该释放不放").
set -eu

# Overridable via Environment= in the unit or /etc/aipc/suspend-gpu-guard.env
BUSY_THRESHOLD="${BUSY_THRESHOLD:-50}"
# Consecutive polls at/above threshold before taking the lock (~10s default).
BUSY_STREAK_NEED="${BUSY_STREAK_NEED:-2}"
# Consecutive polls below threshold before release (~15s default).
IDLE_STREAK_NEED="${IDLE_STREAK_NEED:-3}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
AC_ONLINE_PATH="${AC_ONLINE_PATH:-/sys/class/power_supply/AC0/online}"
INHIBIT_PID=
busy_streak=0
idle_streak=0

find_gpu_busy_file() {
    local f
    for f in /sys/class/drm/card*/device/gpu_busy_percent; do
        [ -r "$f" ] && { echo "$f"; return; }
    done
}

gpu_busy_pct() {
    local v
    v=$(cat "$GPU_BUSY_FILE" 2>/dev/null || echo 0)
    # strip non-digits (sysfs is usually plain int)
    v=${v//[^0-9]/}
    echo "${v:-0}"
}

is_ac_online() {
    [ "$(cat "$AC_ONLINE_PATH" 2>/dev/null || echo 0)" = "1" ]
}

release_inhibit() {
    if [ -n "${INHIBIT_PID:-}" ] && kill -0 "$INHIBIT_PID" 2>/dev/null; then
        # Kill process group: systemd-inhibit + child sleep infinity
        kill -- "-$INHIBIT_PID" 2>/dev/null || kill "$INHIBIT_PID" 2>/dev/null || true
        wait "$INHIBIT_PID" 2>/dev/null || true
        echo "suspend-gpu-guard: released sleep inhibitor (gpu idle/off-AC)"
    fi
    INHIBIT_PID=
}

take_inhibit() {
    if [ -n "${INHIBIT_PID:-}" ] && kill -0 "$INHIBIT_PID" 2>/dev/null; then
        return
    fi
    # setsid so we can kill the whole tree cleanly
    setsid systemd-inhibit --what=sleep --mode=block \
        --who=aipc-suspend-gpu-guard \
        --why="GPU compute busy (gfx1151 resume-from-s2idle hang workaround)" \
        sleep infinity &
    INHIBIT_PID=$!
    echo "suspend-gpu-guard: acquired sleep inhibitor (busy>=${BUSY_THRESHOLD}% for ${BUSY_STREAK_NEED} polls)"
}

cleanup() {
    release_inhibit
    exit 0
}
trap cleanup TERM INT

GPU_BUSY_FILE=$(find_gpu_busy_file)
if [ -z "$GPU_BUSY_FILE" ]; then
    echo "suspend-gpu-guard: no gpu_busy_percent sysfs node found, exiting" >&2
    exit 1
fi
echo "suspend-gpu-guard: watching $GPU_BUSY_FILE threshold=${BUSY_THRESHOLD}% busy_need=${BUSY_STREAK_NEED} idle_need=${IDLE_STREAK_NEED} poll=${POLL_INTERVAL}s"

while true; do
    pct=$(gpu_busy_pct)
    if is_ac_online && [ "$pct" -ge "$BUSY_THRESHOLD" ]; then
        busy_streak=$((busy_streak + 1))
        idle_streak=0
        if [ "$busy_streak" -ge "$BUSY_STREAK_NEED" ]; then
            take_inhibit
        fi
    else
        # Off AC, or below threshold: count toward release
        busy_streak=0
        if [ -n "${INHIBIT_PID:-}" ]; then
            idle_streak=$((idle_streak + 1))
            if [ "$idle_streak" -ge "$IDLE_STREAK_NEED" ] || ! is_ac_online; then
                release_inhibit
                idle_streak=0
            fi
        else
            idle_streak=0
        fi
    fi
    sleep "$POLL_INTERVAL"
done
