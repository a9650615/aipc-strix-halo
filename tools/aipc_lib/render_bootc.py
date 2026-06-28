from __future__ import annotations

from aipc_lib.modules import Module


def render(
    mods: list[Module],
    *,
    base: str,
    image_ref: str,
    build_date: str,
) -> str:
    lines: list[str] = []

    lines.append(f"FROM {base}")
    lines.append(f"ENV AIPC_IMAGE_REF={image_ref}")
    lines.append(f"ENV AIPC_BUILD_DATE={build_date}")
    lines.append("")

    all_pkgs = [pkg for m in mods for pkg in m.packages]
    if all_pkgs:
        lines.append("RUN rpm-ostree install -y \\\n    " + " \\\n    ".join(all_pkgs))
        lines.append("")

    for m in mods:
        for karg in m.kargs:
            lines.append(f"RUN bootc kargs --append={karg}")

        files_dir = m.path / "files"
        if files_dir.is_dir():
            lines.append(f"COPY modules/{m.name}/files/ /")

        modprobe_dir = m.path / "modprobe.d"
        if modprobe_dir.is_dir():
            lines.append(f"COPY modules/{m.name}/modprobe.d/ /etc/modprobe.d/")

        env_dir = m.path / "env"
        if env_dir.is_dir():
            lines.append(f"COPY modules/{m.name}/env/ /etc/aipc/env.d/{m.name}/")

        post = m.path / "post-install.sh"
        if post.exists():
            tmp = f"/tmp/post-install-{m.name}.sh"
            lines.append(f"COPY modules/{m.name}/post-install.sh {tmp}")
            lines.append(f"RUN /bin/sh -eux {tmp} && rm -f {tmp}")

        if m.kargs or files_dir.is_dir() or modprobe_dir.is_dir() or env_dir.is_dir() or post.exists():
            lines.append("")

    lines.append("RUN bootc container lint")
    return "\n".join(lines) + "\n"
