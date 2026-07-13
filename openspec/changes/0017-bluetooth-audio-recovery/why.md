# Why

The paired LG-XT7S Bluetooth speaker repeatedly comes back after reboot in a
BlueZ half-connected state. BlueZ reports the device as connected, but its A2DP
services are unresolved, PipeWire has no `bluez_output`, and audio silently
falls back or disappears. Manual recovery currently requires restarting the
user audio stack and reconnecting the speaker.

The existing WirePlumber routing rule only prioritizes sinks that already
exist; it cannot repair the failed A2DP negotiation.
