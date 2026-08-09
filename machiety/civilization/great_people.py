"""伟人系统：任何智能体可因卓越成就成为伟人，死后留下文化遗产。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.agent import Agent
    from ..engine.scheduler import Game

GREAT_THRESHOLD = 25.0     # 影响力 + 荣誉 达到阈值即可能涌现

# 伟人天赋可落地的全国效果种类
GIFT_KINDS = {"research", "food", "war", "culture", "wealth", "stability"}


@dataclass
class Legacy:
    name: str
    title: str
    legacy: str
    day: int
    kind: str = ""             # 天赋种类，遗产持续泽被后世

    def to_dict(self) -> dict:
        return {"name": self.name, "title": self.title, "legacy": self.legacy,
                "day": self.day, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "Legacy":
        return cls(name=d["name"], title=d["title"], legacy=d["legacy"],
                   day=int(d["day"]), kind=d.get("kind", ""))


class GreatPersonSystem:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.legacies: list[Legacy] = []

    async def check(self, game: "Game", agent: "Agent") -> None:
        """荣誉/影响力足够高的角色涌现为伟人。"""
        if agent.great_title or not agent.alive:
            return
        if agent.influence + agent.honor < GREAT_THRESHOLD:
            return
        if agent.achievement < 1:
            return
        if self.rng.random() > 0.5:
            return
        result = await game.llm.generate("great_person",
                                         {"name": agent.name, "profession": agent.profession,
                                          "tier": "large"})
        agent.great_title = result.get("title", "大贤者")
        agent.great_gift = result.get("gift", "其智慧泽被后世")
        gift_kind = result.get("gift_kind")
        agent.great_gift_kind = gift_kind if gift_kind in GIFT_KINDS else "research"
        agent.influence += 5.0
        agent.remember(f"我被尊为{agent.great_title}：{agent.great_gift}",
                       game.clock.total_hours, importance=9.5)
        game.bus.publish("great_person",
                         f"伟人诞生！{agent.name} 被尊为「{agent.great_title}」—— {agent.great_gift}",
                         tick=game.clock.total_hours, x=agent.x, y=agent.y)

    def on_death(self, game: "Game", agent: "Agent") -> None:
        if not agent.great_title:
            return
        legacy = Legacy(
            name=agent.name, title=agent.great_title,
            legacy=f"{agent.great_title}{agent.name} 留下了不朽的遗产：{agent.great_gift}",
            day=game.clock.day, kind=agent.great_gift_kind or "",
        )
        self.legacies.append(legacy)
        game.bus.publish("legacy", legacy.legacy, tick=game.clock.total_hours)

    def gift_bonus(self, game: "Game", kind: str) -> float:
        """在世伟人天赋 + 已故伟人遗产，对全国该类活动的持续加成。"""
        total = 0.0
        for a in game.manager.alive():
            if a.great_title and a.great_gift_kind == kind:
                total += 0.15
        for legacy in self.legacies:
            if legacy.kind == kind:
                total += 0.08
        return total

    def to_dict(self) -> dict:
        return {"legacies": [l.to_dict() for l in self.legacies]}

    def load_dict(self, data: dict) -> None:
        self.legacies = [Legacy.from_dict(d) for d in data.get("legacies", [])]
