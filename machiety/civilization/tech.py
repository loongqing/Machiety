"""科技与文化：灵感池累积 → 顿悟发明 → 社会传播。无预设科技树。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.scheduler import Game

CATEGORY_NAMES = {"food": "粮食", "war": "战争", "spirit": "精神", "economy": "经济", "build": "建造"}
EPIPHANY_THRESHOLD = 30.0


@dataclass
class Tech:
    name: str
    category: str
    effect: str
    inventor: str
    day: int
    spread: float = 0.0       # 0~1 传播度

    def to_dict(self) -> dict:
        return {"name": self.name, "category": self.category, "effect": self.effect,
                "inventor": self.inventor, "day": self.day, "spread": round(self.spread, 3)}

    @classmethod
    def from_dict(cls, d: dict) -> "Tech":
        return cls(name=d["name"], category=d["category"], effect=d["effect"],
                   inventor=d["inventor"], day=int(d["day"]), spread=float(d.get("spread", 0)))


class TechSystem:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.pool: dict[str, float] = {c: 0.0 for c in CATEGORY_NAMES}
        self.techs: list[Tech] = []
        self.pending_seed: str | None = None    # 玩家 inspire idea 植入的概念

    # ---------------- 灵感

    def add_inspiration(self, category: str, amount: float = 1.0) -> None:
        if category in self.pool:
            self.pool[category] += amount

    def has_tech(self, name: str) -> bool:
        return any(t.name == name for t in self.techs)

    def tech_bonus(self, keyword: str) -> float:
        """已传播科技对某类活动的加成。"""
        bonus = 0.0
        for t in self.techs:
            if keyword in t.effect or keyword in t.name:
                bonus += 0.25 * max(t.spread, 0.3)
        return bonus

    def literacy(self, game: "Game") -> float:
        """识字率：随科技、学宫区域与文化/科研政策缓慢上升。"""
        base = 0.1 + 0.05 * len(self.techs)
        academies = sum(1 for s in game.cities.settlements
                        for d in s.districts if d.done and d.type == "academy")
        base += 0.05 * academies
        base += game.policy.bonus("research") + game.policy.bonus("culture")
        return min(0.95, base)

    # ---------------- 每日推进：传播与顿悟

    async def daily(self, game: "Game") -> None:
        # 传播：受识字率与道路（河流/定居点联通近似）影响
        road_factor = 1.0 + 0.1 * len(game.cities.settlements)
        for tech in self.techs:
            if tech.spread < 1.0:
                tech.spread = min(1.0, tech.spread + 0.03 * self.literacy(game) * road_factor)

        # 灵感阈值 → 顿悟
        for cat, value in sorted(self.pool.items(), key=lambda kv: -kv[1]):
            if value >= EPIPHANY_THRESHOLD:
                self.pool[cat] = 0.0
                await self._epiphany(game, cat)
                break

    async def _epiphany(self, game: "Game", category: str) -> None:
        candidates = [a for a in game.manager.alive()
                      if a.profession in ("scholar", "priest", "artisan", "official")]
        agent = self.rng.choice(candidates or game.manager.alive())
        payload = {"category": category, "agent_name": agent.name,
                   "seed_idea": self.pending_seed or "",
                   "taken": [t.name for t in self.techs], "tier": "large"}
        result = await game.llm.generate("epiphany", payload)
        self.pending_seed = None

        name = result.get("name") or f"{CATEGORY_NAMES.get(category, category)}之法"
        if self.has_tech(name):
            # 灵感枯竭：退回一半灵感，等待下一次顿悟
            self.pool[category] += EPIPHANY_THRESHOLD / 2
            return
        tech = Tech(name=name, category=category,
                    effect=result.get("effect", "社会效率提升"),
                    inventor=agent.name, day=game.clock.day)
        self.techs.append(tech)
        agent.influence += 3.0
        agent.achievement += 1
        agent.remember(f"我顿悟了「{name}」：{tech.effect}", game.clock.total_hours, importance=9.0)
        game.bus.publish("epiphany", f"{agent.name} 顿悟了「{name}」—— {tech.effect}",
                         tick=game.clock.total_hours, x=agent.x, y=agent.y, category=category)

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {"pool": self.pool, "techs": [t.to_dict() for t in self.techs],
                "pending_seed": self.pending_seed}

    def load_dict(self, data: dict) -> None:
        self.pool.update(data.get("pool", {}))
        self.techs = [Tech.from_dict(d) for d in data.get("techs", [])]
        self.pending_seed = data.get("pending_seed")
