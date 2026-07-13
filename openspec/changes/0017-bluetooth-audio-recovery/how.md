# How

Implement the recovery as a stdlib-only Python helper with pure sink-detection
and recovery-decision functions covered by a small `unittest` file. The runtime helper uses existing
host tools (`busctl`, `pactl`, `systemctl --user`, and `wpctl`) and a bounded
poll loop. A user oneshot unit invokes it after the existing audio services.

The target address defaults to the known LG-XT7S address and is overrideable
with `AIPC_BLUETOOTH_AUDIO_MAC` for another paired speaker. A paired but
disconnected speaker gets one normal connect attempt; a half-connected speaker
gets the user-audio restart followed by Bluetooth daemon and adapter reset
fallback. The existing
WirePlumber priority config is copied into the module so its analog fallback
survives image rebuilds.

Build-time installation only sets file modes and the user-unit symlink. Live
verification copies the same files to the running host, reloads the user
manager, and checks a healthy session is a no-op before reboot verification.
