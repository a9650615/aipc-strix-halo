#!/bin/sh
set -eu

# No-op: the renderer's `COPY modules/dev-distrobox-templates/files/ /` step
# already stages node.ini/python.ini directly at /etc/aipc/distrobox/ before
# this script runs. An earlier version of this script tried to re-copy them
# from a /usr/share/aipc/dev-distrobox-templates staging dir that this
# module never populates, using the pre-rename .yaml names (see 4cde9b5) --
# that loop's [ -f ] guard always failed, so it silently did nothing.
# Removed as dead code.
