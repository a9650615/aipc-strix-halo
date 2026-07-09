"""Qt stylesheet utilities for CodexBar progress bars and theming."""

from __future__ import annotations


def get_stylesheet(config: "GuiConfig") -> str:  # noqa: F821
    """Return the full Qt stylesheet for the application."""
    shape = config.progress_bar.shape
    corner_radius = config.progress_bar.corner_radius
    theme = config.progress_bar.theme

    if theme == "light":
        bg = "#f0f0f0"
        fg = "#333333"
        accent = "#4a90d9"
    elif theme == "dark":
        bg = "#2a2a2a"
        fg = "#e0e0e0"
        accent = "#6cb4ee"
    else:
        bg = "#ffffff"
        fg = "#000000"
        accent = "#4a90d9"

    radius = f"{corner_radius}px" if shape == "rounded" else "0px"

    return f"""
QToolTip {{
    background-color: {bg};
    color: {fg};
    border: 1px solid {accent};
    padding: 4px;
    border-radius: {radius};
}}

QLabel {{
    color: {fg};
}}
"""
