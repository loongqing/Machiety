"""侧栏上下文面板与事件流水。"""

from __future__ import annotations

from textual.containers import ScrollableContainer
from textual.widgets import Label, RichLog


class InfoPanel(ScrollableContainer):
    """上下文面板：角色/城市/地块详情、指令回执。长文本可滚动查看。"""

    DEFAULT_CSS = """
    InfoPanel > Label {
        width: auto;
        height: auto;
    }
    """

    def compose(self):
        yield Label("", id="info-content")

    def show_text(self, text: str) -> None:
        self.query_one(Label).update(text)
        self.scroll_home(animate=False)   # 切换内容后回到顶部
        # 内容超出可视区域时自动聚焦，提示可滚动（等布局刷新后再判断尺寸）
        self.call_after_refresh(self._focus_if_overflow)

    def _focus_if_overflow(self) -> None:
        from textual.widgets import Input

        if self.virtual_size.height <= self.size.height:
            return
        focused = self.screen.focused
        if isinstance(focused, Input) or isinstance(focused, Label):
            return    # 用户正在输入或已聚焦面板内容时不打扰
        self.focus()


class EventLog(RichLog):
    """事件流水：战争、突破、伟人诞生……"""

    KIND_ICONS = {
        "combat": "[red]⚔[/red]", "epiphany": "[cyan]✦[/cyan]",
        "policy": "[yellow]§[/yellow]", "wonder": "[magenta]◆[/magenta]",
        "disaster": "[red]✸[/red]", "era": "[bold cyan]❖[/bold cyan]",
        "great_person": "[bold magenta]★[/bold magenta]", "city": "[green]⌂[/green]",
        "death": "[dim]✝[/dim]", "birth": "[green]♥[/green]",
        "miracle": "[bold yellow]☀[/bold yellow]", "rebellion": "[bold red]![/bold red]",
        "founding": "[bold green]⚑[/bold green]", "honor": "[magenta]★[/magenta]",
        "inspire": "[cyan]~[/cyan]", "gift": "[yellow]◈[/yellow]",
        "legacy": "[dim magenta]✦[/dim magenta]", "culture": "[green]♫[/green]",
        "system": "[dim yellow]⚠[/dim yellow]",
    }

    def log_event(self, event) -> None:
        icon = self.KIND_ICONS.get(event.kind, "·")
        self.write(f"{icon} {event.text}")
