"""全局事件总线：模拟中所有值得记录的事件在此汇聚，供 UI 浮层与日志使用。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Event:
    tick: int
    kind: str            # combat / epiphany / policy / wonder / disaster / birth / death / era ...
    text: str
    x: int | None = None
    y: int | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"tick": self.tick, "kind": self.kind, "text": self.text,
                "x": self.x, "y": self.y, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(tick=int(d["tick"]), kind=d["kind"], text=d["text"],
                   x=d.get("x"), y=d.get("y"), data=dict(d.get("data") or {}))


# 值得载入编年史的重大事件类型
CHRONICLE_KINDS = {"epiphany", "era", "wonder", "great_person", "rebellion",
                   "founding", "disaster", "policy", "city"}


class EventBus:
    def __init__(self, maxlen: int = 2000) -> None:
        self.log: deque[Event] = deque(maxlen=maxlen)
        self.chronicle: list[Event] = []       # 国史：重大事件永久留档
        self._subs: list[Callable[[Event], None]] = []

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subs.append(fn)

    def unsubscribe(self, fn: Callable[[Event], None]) -> None:
        if fn in self._subs:
            self._subs.remove(fn)

    def publish(self, kind: str, text: str, *, tick: int = 0,
                x: int | None = None, y: int | None = None, **data) -> Event:
        event = Event(tick=tick, kind=kind, text=text, x=x, y=y, data=data)
        self.log.append(event)
        if kind in CHRONICLE_KINDS:
            self.chronicle.append(event)
            if len(self.chronicle) > 500:
                self.chronicle = self.chronicle[-500:]
        for fn in list(self._subs):
            try:
                fn(event)
            except Exception:
                pass
        return event

    def recent(self, n: int = 20) -> list[Event]:
        return list(self.log)[-n:]
