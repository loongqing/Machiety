"""奇观工程：跨代巨型项目，进度受国力影响，可能烂尾。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.scheduler import Game

WONDER_COST = 600.0
STALL_LIMIT_DAYS = 60      # 连续无进展超过该天数即烂尾
EFFECT_KINDS = {"food_bonus", "research_bonus", "explore_bonus", "trade_bonus"}


@dataclass
class Wonder:
    name: str
    started_day: int
    progress: float = 0.0
    status: str = "building"     # building / completed / abandoned
    effect: str | None = None
    stall_days: int = 0

    @property
    def percent(self) -> int:
        return min(100, int(self.progress / WONDER_COST * 100))

    def to_dict(self) -> dict:
        return {"name": self.name, "started_day": self.started_day,
                "progress": round(self.progress, 1), "status": self.status,
                "effect": self.effect, "stall_days": self.stall_days}

    @classmethod
    def from_dict(cls, d: dict) -> "Wonder":
        return cls(name=d["name"], started_day=int(d["started_day"]),
                   progress=float(d.get("progress", 0)), status=d.get("status", "building"),
                   effect=d.get("effect"), stall_days=int(d.get("stall_days", 0)))


class WonderSystem:
    def __init__(self) -> None:
        self.wonders: list[Wonder] = []
        self.bonuses: dict[str, float] = {}     # food_bonus / research_bonus ...

    def active(self) -> Wonder | None:
        return next((w for w in self.wonders if w.status == "building"), None)

    def launch(self, game: "Game", name: str, visionary: str | None = None) -> str:
        if self.active():
            return f"已有奇观「{self.active().name}」在建造中，国力不足以同时开工两项"
        w = Wonder(name=name, started_day=game.clock.day)
        self.wonders.append(w)
        if visionary:
            game.bus.publish("wonder", f"远见者 {visionary} 倡议修建奇观「{name}」，举国响应开工",
                             tick=game.clock.total_hours)
        else:
            game.bus.publish("wonder", f"神谕立项：奇观「{name}」开工！举国动员",
                             tick=game.clock.total_hours)
        return f"奇观「{name}」正式立项，工匠们已开始奠基"

    async def _maybe_visionary_launch(self, game: "Game") -> None:
        """远见角色（高影响力的学者/官员/祭司）自发倡议跨代奇观工程。"""
        citizens = [a for a in game.manager.alive() if not a.is_foreign]
        # 文明需初具规模（进入古典时代后）才会孕育远见
        if len(citizens) < 12 or game.epoch.era_index < 1:
            return
        visionaries = [a for a in citizens
                       if a.profession in ("scholar", "official", "priest") and a.influence >= 5]
        if not visionaries or game.rng.random() > 0.08:
            return
        leader = max(visionaries, key=lambda a: a.influence)
        result = await game.llm.generate("wonder_launch", {"name": leader.name, "tier": "large"})
        wonder_name = result.get("name") or f"{leader.name}之塔"
        leader.influence += 2.0
        leader.achievement += 1
        leader.remember(f"我倡议修建奇观「{wonder_name}」，愿倾尽毕生之力",
                        game.clock.total_hours, importance=8.5)
        self.launch(game, wonder_name, visionary=leader.name)

    async def daily(self, game: "Game") -> None:
        if self.active() is None:
            await self._maybe_visionary_launch(game)
        w = self.active()
        if w is None:
            return
        pop = len([a for a in game.manager.alive() if not a.is_foreign])
        gain = pop * 0.06 * (1.0 + 0.1 * len(game.tech.techs))
        if pop < 5:
            gain = 0.0
        w.progress += gain
        if gain < 1.0:
            w.stall_days += 1
        else:
            w.stall_days = 0
        if w.stall_days >= STALL_LIMIT_DAYS:
            w.status = "abandoned"
            # 烂尾工地化作废墟：首都格永久标记，附近民众留下阴影记忆
            capital = next((s for s in game.cities.settlements if not s.foreign), None)
            capital = capital or (game.cities.settlements[0] if game.cities.settlements else None)
            cx = cy = None
            if capital:
                cx, cy = capital.x, capital.y
                tile = game.world.tile(cx, cy)
                if tile:
                    tile.ruins = True
                for a in game.manager.alive():
                    if abs(a.x - cx) + abs(a.y - cy) <= 2:
                        a.remember(f"（深植的记忆）奇观「{w.name}」烂尾了，工地化作废墟，令人扼腕",
                                   game.clock.total_hours, importance=8.5)
                        a.needs["self_actualization"] = max(
                            0.0, a.needs["self_actualization"] - 0.1)
            game.bus.publish("wonder", f"奇观「{w.name}」因国力衰微而烂尾，工地长满荒草",
                             tick=game.clock.total_hours, x=cx, y=cy)
            return
        if w.progress >= WONDER_COST:
            w.status = "completed"
            result = await game.llm.generate("wonder_effect", {"name": w.name, "tier": "large"})
            effect = result.get("effect")
            w.effect = effect if effect in EFFECT_KINDS else "food_bonus"
            self.bonuses[w.effect] = self.bonuses.get(w.effect, 0.0) + 0.25
            capital = next((s for s in game.cities.settlements if not s.foreign), None)
            capital = capital or (game.cities.settlements[0] if game.cities.settlements else None)
            game.bus.publish("wonder", result.get("text", f"奇观「{w.name}」落成！"),
                             tick=game.clock.total_hours,
                             x=capital.x if capital else None,
                             y=capital.y if capital else None)

    def describe(self) -> str:
        if not self.wonders:
            return "尚无奇观工程。使用 launch wonder \"名称\" 立项。"
        lines = []
        for w in self.wonders:
            state = {"building": "建造中", "completed": "已落成", "abandoned": "已烂尾"}[w.status]
            lines.append(f"「{w.name}」 {state} [{w.percent}%] 开工于第{w.started_day}日")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"wonders": [w.to_dict() for w in self.wonders], "bonuses": self.bonuses}

    def load_dict(self, data: dict) -> None:
        self.wonders = [Wonder.from_dict(d) for d in data.get("wonders", [])]
        self.bonuses = dict(data.get("bonuses", {}))
