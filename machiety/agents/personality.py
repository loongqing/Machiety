"""大五人格：决定角色的决策风格。"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict


@dataclass
class Personality:
    openness: float = 0.5            # 开放性
    conscientiousness: float = 0.5   # 尽责性
    extraversion: float = 0.5        # 外向性
    agreeableness: float = 0.5       # 宜人性
    neuroticism: float = 0.5         # 神经质

    @classmethod
    def generate(cls, rng: random.Random) -> "Personality":
        return cls(**{f.name: round(rng.random(), 2)
                      for f in cls.__dataclass_fields__.values()})

    def describe(self) -> str:
        parts = []
        if self.openness > 0.7:
            parts.append("富于想象力")
        elif self.openness < 0.3:
            parts.append("因循守旧")
        if self.conscientiousness > 0.7:
            parts.append("勤勉自律")
        elif self.conscientiousness < 0.3:
            parts.append("随性懒散")
        if self.extraversion > 0.7:
            parts.append("热情外向")
        elif self.extraversion < 0.3:
            parts.append("沉默寡言")
        if self.agreeableness > 0.7:
            parts.append("宽厚友善")
        elif self.agreeableness < 0.3:
            parts.append("好斗多疑")
        if self.neuroticism > 0.7:
            parts.append("敏感易怒")
        elif self.neuroticism < 0.3:
            parts.append("沉稳淡定")
        return "、".join(parts) if parts else "性情平常"

    def conflict_power(self) -> float:
        """冲突中的基础实力系数。"""
        return 1.0 + (self.extraversion + self.conscientiousness - self.neuroticism) * 0.3

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Personality":
        return cls(**{k: float(data.get(k, 0.5)) for k in cls.__dataclass_fields__})
