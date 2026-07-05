#!/bin/bash
set -eu

BUSY_THRESHOLD=15
POLL_INTERVAL=5
AC_ONLINE_PATH=/sys/class/power_supply/AC0/online
INHIBIT_PID=

find_gpu_busy_file() {
    local f
    for f in /sys/class/drm/card*/device/gpu_busy_percent; do
        [ -r "$f" ] && { echo "$f"; return; }
    done
}

is_busy() {
    [ -n "$GPU_BUSY_FILE" ] && [ "$(cat "$GPU_BUSY_FILE")" -ge "$BUSY_THRESHOLD" ]
}

is_ac_online() {
    [ "$(cat "$AC_ONLINE_PATH" 2>/dev/null)" = "1" ]
}

release_inhibit() {
    if [ -n "$INHIBIT_PID" ] && kill -0 "$INHIBIT_PID" 2>/dev/null; then
        kill "$INHIBIT_PID" 2>/dev/null || true
    fi
    INHIBIT_PID=
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
echo "suspend-gpu-guard: watching $GPU_BUSY_FILE (threshold ${BUSY_THRESHOLD}%)"

while true; do
    if is_ac_online && is_busy; then
        if [ -z "$INHIBIT_PID" ] || ! kill -0 "$INHIBIT_PID" 2>/dev/null; then
            systemd-inhibit --what=sleep --mode=block \
                --who=aipc-suspend-gpu-guard \
                --why="GPU compute busy (gfx1151 resume-from-s2idle hang workaround)" \
                sleep infinity &
            INHIBIT_PID=$!
        fi
    else
        # Off AC, or GPU idle: never hold the lock. On battery this means
        # normal system sleep (idle timeout, lid close, manual) proceeds
        # unblocked -- no need to force it ourselves, only to stop getting
        # in its way.
        release_inhibit
    fi
    sleep "$POLL_INTERVAL"
done
