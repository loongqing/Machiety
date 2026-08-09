"""游戏历法：1 tick = 1 游戏小时。"""

from __future__ import annotations

HOURS_PER_DAY = 24
DAYS_PER_YEAR = 360
DAWN = 6      # 黎明：每日需求更新
DUSK = 18     # 黄昏：智能体反思与记忆压缩


class Clock:
    def __init__(self, total_hours: int = 0) -> None:
        self.total_hours = total_hours

    def tick(self) -> None:
        self.total_hours += 1

    @property
    def hour(self) -> int:
        return self.total_hours % HOURS_PER_DAY

    @property
    def day(self) -> int:
        """自纪元开始的第几天（0 起）。"""
        return self.total_hours // HOURS_PER_DAY

    @property
    def year(self) -> int:
        return self.day // DAYS_PER_YEAR + 1

    @property
    def day_of_year(self) -> int:
        return self.day % DAYS_PER_YEAR + 1

    @property
    def is_dawn(self) -> bool:
        return self.hour == DAWN

    @property
    def is_dusk(self) -> bool:
        return self.hour == DUSK

    @property
    def is_night(self) -> bool:
        return self.hour >= 21 or self.hour < DAWN

    @property
    def date_str(self) -> str:
        return f"纪元{self.year}年 第{self.day_of_year}日 {self.hour:02d}:00"

    def to_dict(self) -> dict:
        return {"total_hours": self.total_hours}

    @classmethod
    def from_dict(cls, data: dict) -> "Clock":
        return cls(total_hours=int(data.get("total_hours", 0)))
