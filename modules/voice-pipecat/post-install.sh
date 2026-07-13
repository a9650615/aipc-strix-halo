#!/bin/sh
# post-install.sh — voice-pipecat
# BUILD-TIME ONLY. No services started, no listeners probed.
set -eu

chmod +x /usr/bin/aipc-voice-once
chmod +x /usr/bin/aipc-voice-stream
chmod +x /usr/bin/aipc-voice-template
chmod +x /usr/bin/aipc-voice-say
chmod +x /etc/aipc/aipc-bluetooth-audio-recover
mkdir -p /var/lib/aipc-voice/persona/templates

# Enable the overlay user service declaratively (build-time symlink, no daemon).
# This is the SINGLE launcher — the KDE autostart .desktop was removed because
# running both spawned a duplicate overlay whose autostart instance escaped the
# service cgroup and lingered as an orphan (systemctl restart could not reap it).
mkdir -p /usr/lib/systemd/user/default.target.wants
ln -sf ../aipc-voice-overlay.service \
    /usr/lib/systemd/user/default.target.wants/aipc-voice-overlay.service
ln -sf ../aipc-bluetooth-audio-recover.service \
    /usr/lib/systemd/user/default.target.wants/aipc-bluetooth-audio-recover.service
