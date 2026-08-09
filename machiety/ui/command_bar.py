"""底部命令栏：支持历史（↑/↓）与 Tab 补全。"""

from __future__ import annotations

from textual.binding import Binding
from textual.suggester import SuggestFromList
from textual.widgets import Input

from ..commands.parser import COMMAND_NAMES


class CommandBar(Input):
    """底部命令栏：支持历史（↑/↓）与 Tab 补全。"""

    BINDINGS = [
        Binding("up", "history_prev", "上一条指令", show=False),
        Binding("down", "history_next", "下一条指令", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(
            placeholder='输入指令，如 miracle "雨水将赐福此地"（help 查看全部）',
            suggester=SuggestFromList(COMMAND_NAMES),
            **kwargs,
        )
        self.command_history: list[str] = []
        self._history_pos: int | None = None
        self._draft = ""

    def record(self, text: str) -> None:
        """提交成功后记入历史。"""
        text = text.strip()
        if not text or (self.command_history and self.command_history[-1] == text):
            return
        self.command_history.append(text)
        if len(self.command_history) > 100:
            self.command_history = self.command_history[-100:]
        self._history_pos = None
        self._draft = ""

    def action_history_prev(self) -> None:
        if not self.command_history:
            return
        if self._history_pos is None:
            self._draft = self.value
            self._history_pos = len(self.command_history) - 1
        elif self._history_pos > 0:
            self._history_pos -= 1
        self.value = self.command_history[self._history_pos]
        self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        if self._history_pos is None:
            return
        if self._history_pos < len(self.command_history) - 1:
            self._history_pos += 1
            self.value = self.command_history[self._history_pos]
        else:
            self._history_pos = None
            self.value = self._draft
        self.cursor_position = len(self.value)
