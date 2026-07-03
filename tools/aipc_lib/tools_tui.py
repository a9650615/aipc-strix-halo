from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, RichLog, Static

from aipc_lib.tools_menu import CATEGORIES, Tool


class ToolRow(Static):
    """One tool: [x]/[ ] mark + name + a plain Install button.

    Mouse-clickable and keyboard-focusable (Tab/Shift+Tab to move focus,
    Enter/Space to activate) — same effect either way.
    """

    def __init__(self, tool: Tool) -> None:
        super().__init__()
        self.tool = tool
        self.installed = tool.is_installed()

    def compose(self) -> ComposeResult:
        yield Static(self._label(), classes="tool-label", id=f"label-{self._safe_id()}")
        yield Button(
            "Installed" if self.installed else "Install",
            id=f"install-{self._safe_id()}",
            disabled=self.installed,
        )

    def _safe_id(self) -> str:
        return self.tool.name.replace(" ", "-").replace("(", "").replace(")", "")

    def _label(self) -> str:
        mark = "[x]" if self.installed else "[ ]"
        return f"{mark} {self.tool.name}"


class CategoryBlock(Static):
    """Label column on the left, tools stacked on the right — a plain
    two-column checklist row, one per category."""

    def __init__(self, name: str, tools: list[Tool]) -> None:
        super().__init__()
        self.category_name = name
        self.tools = tools

    def compose(self) -> ComposeResult:
        with Horizontal(classes="category-row"):
            yield Static(self.category_name, classes="category-label")
            with Vertical(classes="tools-column"):
                for tool in self.tools:
                    yield ToolRow(tool)


class ToolsApp(App):
    """aipc config tools — plain checklist, keyboard + mouse.

    Deliberately plain: bordered rows, no color theming or animation —
    just a label column and a list of [x]/[ ] rows per category, each
    with a focusable Install button.
    """

    CSS = """
    Screen {
        background: $surface;
    }
    .title {
        padding: 1 2 0 2;
        text-style: bold;
    }
    .category-row {
        height: auto;
        border-bottom: solid $foreground 20%;
        padding: 1 2;
    }
    .category-label {
        width: 14;
        color: $text-muted;
        border-right: solid $foreground 20%;
        padding-right: 1;
    }
    .tools-column {
        width: 1fr;
        padding-left: 2;
    }
    ToolRow {
        layout: horizontal;
        height: 3;
        align: left middle;
    }
    .tool-label {
        width: 1fr;
        content-align: left middle;
    }
    Button {
        min-width: 14;
        background: $surface;
        border: round $foreground 50%;
    }
    #log {
        height: 8;
        border: round $foreground 30%;
        margin: 1 2;
    }
    .hint {
        color: $text-muted;
        padding: 0 2 1 2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh status"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("aipc config tools", classes="title")
        with ScrollableContainer():
            for category, tools in CATEGORIES.items():
                yield CategoryBlock(category, tools)
        yield RichLog(id="log")
        yield Static("q quit   r refresh   tab / click to install", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).write("Ready. Click Install, or Tab + Enter.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        row = event.button.parent
        if not isinstance(row, ToolRow):
            return
        self._install(row, event.button)

    @work(thread=True)
    def _install(self, row: ToolRow, button: Button) -> None:
        log = self.query_one("#log", RichLog)
        self.call_from_thread(log.write, f"Installing {row.tool.name}...")
        self.call_from_thread(setattr, button, "disabled", True)
        result = row.tool.install()
        if result.returncode == 0:
            self.call_from_thread(log.write, f"{row.tool.name}: installed")
            self.call_from_thread(setattr, button, "label", "Installed")
        else:
            self.call_from_thread(
                log.write, f"{row.tool.name}: failed (exit {result.returncode})"
            )
            self.call_from_thread(setattr, button, "disabled", False)

    def action_refresh_all(self) -> None:
        for row in self.query(ToolRow):
            row.installed = row.tool.is_installed()
            label = row.query_one(".tool-label", Static)
            label.update(row._label())
            button = row.query_one(Button)
            if row.installed:
                button.label = "Installed"
                button.disabled = True


def run() -> None:
    ToolsApp().run()
