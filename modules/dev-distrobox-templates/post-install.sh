#!/bin/sh
set -eu

tpl_dir=/etc/aipc/distrobox
src_dir=/usr/share/aipc/dev-distrobox-templates

mkdir -p "${tpl_dir}"
for tpl in node.yaml python.yaml; do
  if [ -f "${src_dir}/${tpl}" ]; then
    cp "${src_dir}/${tpl}" "${tpl_dir}/${tpl}"
  fi
done
