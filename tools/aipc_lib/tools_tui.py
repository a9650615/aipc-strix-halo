from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Button, Footer, Header, RichLog, Static

from aipc_lib.tools_menu import CATEGORIES, Tool


class ToolRow(Static):
    """One tool: name/status label + an Install button (mouse-clickable,
    keyboard-focusable — Tab/Shift+Tab to move focus, Enter/Space to
    activate, same as clicking)."""

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
            variant="success" if self.installed else "primary",
        )

    def _safe_id(self) -> str:
        return self.tool.name.replace(" ", "-").replace("(", "").replace(")", "")

    def _label(self) -> str:
        mark = "[green]✓[/green]" if self.installed else "[yellow]○[/yellow]"
        return f"{mark} {self.tool.name}"


class ToolsApp(App):
    """aipc config tools — categorized install checklist, keyboard + mouse.

    Textual (same author as rich, already a dependency) instead of plain
    sequential y/N prompts: supports arrow-key/Tab navigation and mouse
    clicks, closer to how the user asked for this to feel ("像 claude
    code"). Bind() calls below are the keyboard side; every Button is
    natively mouse-clickable without extra wiring.
    """

    CSS = """
    ToolRow {
        layout: horizontal;
        height: 3;
        align: left middle;
    }
    .tool-label {
        width: 1fr;
        content-align: left middle;
    }
    #log {
        height: 10;
        border: solid $accent;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_all", "Refresh status"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with ScrollableContainer():
            for category, tools in CATEGORIES.items():
                yield Static(f"[bold]{category}[/bold]", classes="category-header")
                with Vertical():
                    for tool in tools:
                        yield ToolRow(tool)
        yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

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
            self.call_from_thread(log.write, f"[green]{row.tool.name}: installed[/green]")
            self.call_from_thread(setattr, button, "label", "Installed")
            self.call_from_thread(setattr, button, "variant", "success")
        else:
            self.call_from_thread(
                log.write, f"[red]{row.tool.name}: failed (exit {result.returncode})[/red]"
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
                button.variant = "success"
                button.disabled = True


def run() -> None:
    ToolsApp().run()
