"""Textual 主应用：四区布局 + 模拟循环 + 指令执行。"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input

from ..commands.effects import execute_command
from ..commands.parser import HELP_TEXT, parse_command
from ..engine.events import Event
from .command_bar import CommandBar
from .legend import LegendBar
from .map_view import MapView
from .side_panel import EventLog, InfoPanel
from .status_bar import StatusBar

TICK_SECONDS = 0.35          # 每游戏小时的现实间隔
NOTIFY_KINDS = {"epiphany", "era", "wonder", "great_person", "rebellion",
                "disaster", "founding", "miracle", "prayer", "granted"}


class MachietyApp(App):
    TITLE = "Machiety"
    SUB_TITLE = "终端中的文明实验室"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("up", "cursor(0,-1)", "光标↑", show=False),
        Binding("down", "cursor(0,1)", "光标↓", show=False),
        Binding("left", "cursor(-1,0)", "光标←", show=False),
        Binding("right", "cursor(1,0)", "光标→", show=False),
        Binding("enter", "inspect", "查看详情"),
        Binding("w", "watch_here", "追踪角色"),
        Binding("m", "toggle_view", "切换视图"),
        Binding("z", "zoom", "缩放"),
        Binding("space", "pause", "暂停/继续"),
        Binding("ctrl+q", "quit", "退出"),
    ]

    def __init__(self, game, tick_seconds: float = TICK_SECONDS) -> None:
        super().__init__()
        self.game = game
        self.tick_seconds = tick_seconds
        self.paused = False
        self._ticking = False
        self.last_result = ""       # 最近一次指令回执
        self._last_hour = -1        # 节流刷新：记录上次渲染对应的游戏时刻
        self._last_event_count = 0
        self._panel_follow_watch = False   # 侧栏是否处于追踪跟随模式

    # ---------------- 布局

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with Horizontal(id="main-area"):
            with Vertical(id="map-area"):
                yield MapView(self.game, id="map-view")
                yield LegendBar(id="map-legend")
            with Vertical(id="right-pane"):
                yield InfoPanel(id="info-panel")
                yield EventLog(id="event-log", wrap=True, markup=True)
        yield CommandBar(id="command-bar")

    def on_mount(self) -> None:
        self.game.bus.subscribe(self._on_game_event)
        self.query_one(StatusBar).update_status(self.game)
        self.query_one(InfoPanel).show_text(
            f"欢迎降临 Machiety。\n\n{HELP_TEXT}")
        log = self.query_one(EventLog)
        for event in self.game.bus.recent(10):
            log.log_event(event)
        self.set_interval(self.tick_seconds, self._tick)

    # ---------------- 模拟循环

    async def _tick(self) -> None:
        if self.paused or self._ticking:
            return
        self._ticking = True
        try:
            await self.game.step()
        except Exception as e:  # noqa: BLE001 - 模拟异常不应击溃界面
            self.notify(f"模拟异常：{e}", severity="error")
        finally:
            self._ticking = False
        # 节流：仅当游戏时刻推进或有新事件时才刷新界面
        hour_changed = self.game.clock.total_hours != self._last_hour
        new_events = len(self.game.bus.log) != self._last_event_count
        if hour_changed or new_events:
            self.query_one(MapView).dirty = True
            self._refresh_ui()

    def _refresh_ui(self) -> None:
        self._last_hour = self.game.clock.total_hours
        self._last_event_count = len(self.game.bus.log)
        self.query_one(StatusBar).update_status(self.game)
        view = self.query_one(MapView)
        if view.dirty:
            view.refresh()
            view.dirty = False
        watched = self.game.watched
        if self._panel_follow_watch and watched:
            info = self._describe_watched(watched)
            if info:
                self.query_one(InfoPanel).show_text(info)

    def _describe_watched(self, target: str) -> str:
        agent = self.game.manager.by_name(target)
        if agent:
            memories = "\n".join(f"  · {m.text}" for m in agent.memory.recent(5))
            return f"{agent.describe()}\n最近记忆：\n{memories}"
        s = self.game.cities.by_name(target)
        if s:
            return self.game.cities.describe(self.game, s)
        return ""

    def _on_game_event(self, event: Event) -> None:
        try:
            self.query_one(EventLog).log_event(event)
            if event.kind == "combat" and event.x is not None and event.y is not None:
                self.query_one(MapView).add_flash(event.x, event.y)
            if event.kind in NOTIFY_KINDS:
                self.notify(event.text, timeout=6)
        except Exception:
            pass

    # ---------------- 键位动作

    def action_cursor(self, dx: int, dy: int) -> None:
        if self.focused and isinstance(self.focused, CommandBar):
            return  # 焦点在命令栏时方向键归输入框
        self.query_one(MapView).move_cursor(dx, dy)

    def action_inspect(self) -> None:
        if self.focused and isinstance(self.focused, CommandBar):
            return
        self._panel_follow_watch = False    # 手动查看详情优先于追踪
        self.query_one(InfoPanel).show_text(self.query_one(MapView).cursor_info())

    def _watch_target(self, name: str) -> None:
        """进入追踪跟随模式：等价执行 watch <name> 的界面效果。"""
        self.game.watched = name
        self._panel_follow_watch = True
        self.notify(f"追踪 {name}")
        info = self._describe_watched(name)
        if info:
            self.query_one(InfoPanel).show_text(info)

    def action_watch_here(self) -> None:
        """w：追踪光标处的第一个角色；无人则取消追踪。"""
        if self.focused and isinstance(self.focused, CommandBar):
            return
        view = self.query_one(MapView)
        here = self.game.manager.agents_at(view.cursor_x, view.cursor_y)
        if here:
            self._watch_target(here[0].name)
        else:
            self.game.watched = None
            self._panel_follow_watch = False
            self.notify("已取消追踪")

    def on_map_view_tile_clicked(self, event: MapView.TileClicked) -> None:
        """点击地块等价 watch：角色 > 定居点；空地取消追踪。"""
        here = self.game.manager.agents_at(event.x, event.y)
        if here:
            self._watch_target(here[0].name)
            return
        tile = self.game.world.tile(event.x, event.y)
        settlement = next((s for s in self.game.cities.settlements
                           if tile and s.id == tile.settlement_id), None)
        if settlement is not None:
            self._watch_target(settlement.name)
        elif self.game.watched:
            self.game.watched = None
            self._panel_follow_watch = False
            self.notify("已取消追踪")

    def action_toggle_view(self) -> None:
        self.query_one(MapView).toggle_mode()

    def action_zoom(self) -> None:
        self.query_one(MapView).toggle_zoom()

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.notify("时间已冻结" if self.paused else "时间继续流动")

    # ---------------- 退出与自动保存

    def save_current(self, notify_user: bool = False) -> str | None:
        """保存当前槽位（未命名用 autosave），返回槽位名；失败返回 None。"""
        try:
            from ..persistence.saver import save_game
            name = self.game.current_slot or "autosave"
            save_game(self.game, name)
            self.game.current_slot = name
            if notify_user:
                self.notify(f"已自动存档「{name}」")
            return name
        except Exception:  # noqa: BLE001 - 存档失败不应阻断退出
            if notify_user:
                self.notify("自动存档失败", severity="error")
            return None

    async def action_quit(self) -> None:
        self.save_current(notify_user=True)
        await super().action_quit()   # Textual 的 action_quit 是协程，必须 await

    # ---------------- 指令

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "command-bar":
            return
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        cmd = parse_command(text)
        if cmd is None:
            return
        result = await execute_command(self.game, cmd)
        self.last_result = result.text
        self.query_one(CommandBar).record(text)
        if result.new_game is not None:
            self.set_game(result.new_game)
        panel = self.query_one(InfoPanel)
        if cmd.name == "watch" and self.game.watched:
            self._panel_follow_watch = True
            panel.show_text(self._describe_watched(self.game.watched) or result.text)
        else:
            self._panel_follow_watch = False   # 指令输出优先于追踪面板
            panel.show_text(result.text)
        self.query_one(EventLog).write(f"[bold cyan]> {text}[/bold cyan]")
        self.query_one(MapView).dirty = True
        self._refresh_ui()
        if result.quit_app:
            self.save_current(notify_user=True)
            self.exit()

    def set_game(self, new_game) -> None:
        """load 指令后整体替换世界。"""
        self.game.bus.unsubscribe(self._on_game_event)
        self.game = new_game
        self.game.bus.subscribe(self._on_game_event)
        self.query_one(MapView).game = new_game
        self.query_one(MapView).dirty = True
        self._last_hour = -1
        self._last_event_count = 0
        self._panel_follow_watch = bool(new_game.watched)
        self.query_one(EventLog).clear()
        self.query_one(EventLog).write("[bold]存档已载入，世界重启[/bold]")
