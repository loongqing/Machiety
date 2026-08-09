"""城市与区域：定居点由居民自主发展，区域/建筑按共同需求提议修建。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..agents.agent import Agent

if TYPE_CHECKING:
    from ..engine.scheduler import Game

DISTRICT_TYPES = {
    "market": ("市场", "trade"),
    "academy": ("学宫", "education"),
    "holy_site": ("圣地", "faith"),
    "industrial": ("工业区", "production"),
    "harbor": ("港口", "trade"),
    "theater": ("剧院广场", "culture"),
}
DISTRICT_COST = 100          # 完工所需劳动点数

CITY_SUFFIX = ["城", "堡", "镇", "港", "丘"]
CITY_ROOTS = ["晨曦", "磐石", "白鸦", "长河", "星落", "铁杉", "雾湾", "金穗"]


@dataclass
class District:
    type: str
    progress: float = 0.0
    done: bool = False

    def to_dict(self) -> dict:
        return {"type": self.type, "progress": round(self.progress, 1), "done": self.done}

    @classmethod
    def from_dict(cls, d: dict) -> "District":
        return cls(type=d["type"], progress=float(d["progress"]), done=bool(d["done"]))


@dataclass
class Settlement:
    id: int
    name: str
    x: int
    y: int
    founded_day: int
    food_stock: float = 20.0
    districts: list[District] = field(default_factory=list)
    building: District | None = None
    foreign: bool = False          # 外邦城邦（未并入本国）

    @property
    def done_districts(self) -> list[District]:
        return [d for d in self.districts if d.done]

    def district_names(self) -> str:
        names = [DISTRICT_TYPES[d.type][0] for d in self.done_districts]
        return "、".join(names) if names else "尚无区域"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "x": self.x, "y": self.y,
                "founded_day": self.founded_day, "food_stock": round(self.food_stock, 1),
                "districts": [d.to_dict() for d in self.districts],
                "building": self.building.to_dict() if self.building else None,
                "foreign": self.foreign}

    @classmethod
    def from_dict(cls, d: dict) -> "Settlement":
        s = cls(id=int(d["id"]), name=d["name"], x=int(d["x"]), y=int(d["y"]),
                founded_day=int(d["founded_day"]), food_stock=float(d.get("food_stock", 0)))
        s.districts = [District.from_dict(x) for x in d.get("districts", [])]
        s.building = District.from_dict(d["building"]) if d.get("building") else None
        s.foreign = bool(d.get("foreign", False))
        return s


class CitySystem:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.settlements: list[Settlement] = []
        self._next_id = 1

    def new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def by_name(self, name: str) -> Settlement | None:
        return next((s for s in self.settlements if s.name == name), None)

    def nearest(self, x: int, y: int, radius: int = 3) -> Settlement | None:
        best, best_d = None, radius + 1
        for s in self.settlements:
            d = abs(s.x - x) + abs(s.y - y)
            if d <= radius and d < best_d:
                best, best_d = s, d
        return best

    def population(self, game: "Game", s: Settlement) -> int:
        return len([a for a in game.manager.alive() if a.settlement_id == s.id])

    # ---------------- 建城：足够多角色聚居在无城之地

    def maybe_found(self, game: "Game") -> None:
        clusters: dict[tuple[int, int], list] = {}
        for a in game.manager.alive():
            if self.nearest(a.x, a.y, radius=4) is None:
                clusters.setdefault((a.x, a.y), []).append(a)
        for (x, y), members in clusters.items():
            if len(members) >= 4:
                self.found(game, x, y)
                break

    def found(self, game: "Game", x: int, y: int, name: str | None = None) -> Settlement:
        sid = self.new_id()
        name = name or self.rng.choice(CITY_ROOTS) + self.rng.choice(CITY_SUFFIX)
        s = Settlement(id=sid, name=name, x=x, y=y, founded_day=game.clock.day)
        self.settlements.append(s)
        tile = game.world.tile(x, y)
        if tile:
            tile.settlement_id = sid
        for a in game.manager.alive():
            if abs(a.x - x) + abs(a.y - y) <= 3 and a.settlement_id is None:
                a.settlement_id = sid
        game.bus.publish("city", f"聚居者建立了定居点「{name}」（{x},{y}）",
                         tick=game.clock.total_hours, x=x, y=y)
        return s

    # ---------------- 开局：在地图边缘生成外邦城邦

    def spawn_city_states(self, game: "Game", n: int = 2) -> None:
        """在地图边缘可通行处生成独立城邦，含外邦 NPC（不跑完整 LLM 行动循环）。"""
        w, h = game.world.width, game.world.height
        reachable = self._reachable_from(game, game.spawn_x, game.spawn_y)
        edge = [t for t in game.world.tiles
                if t.passable and (t.x, t.y) in reachable
                and (t.x < 4 or t.y < 4 or t.x >= w - 4 or t.y >= h - 4)]
        self.rng.shuffle(edge)
        created = 0
        for t in edge:
            if created >= n:
                break
            if self.nearest(t.x, t.y, radius=10) is not None:
                continue
            sid = self.new_id()
            name = self.rng.choice(CITY_ROOTS) + self.rng.choice(["远邦", "彼岸", "异邦"])
            s = Settlement(id=sid, name=name, x=t.x, y=t.y,
                           founded_day=game.clock.day, food_stock=30.0, foreign=True)
            self.settlements.append(s)
            t.settlement_id = sid
            for _ in range(self.rng.randint(5, 8)):
                # 城民就近散布：中心格 1 人，其余落附近空位，避免全部叠在城邦格
                x, y = t.x, t.y
                for nt in sorted(game.world.tiles_in_radius(t.x, t.y, 3),
                                 key=lambda q: abs(q.x - t.x) + abs(q.y - t.y)):
                    if nt.passable and not game.manager.agents_at(nt.x, nt.y):
                        x, y = nt.x, nt.y
                        break
                else:
                    # 城邦周围已满：由近及远扩大搜索
                    for nt in sorted(game.world.tiles_in_radius(t.x, t.y, 8),
                                     key=lambda q: abs(q.x - t.x) + abs(q.y - t.y)):
                        if nt.passable and not game.manager.agents_at(nt.x, nt.y):
                            x, y = nt.x, nt.y
                            break
                npc = Agent.spawn(game.manager.new_id(), self.rng, x, y,
                                  tick=game.clock.total_hours)
                npc.is_foreign = True
                npc.settlement_id = sid
                npc.remember(f"我是「{name}」的城民，生于斯长于斯。",
                             game.clock.total_hours, importance=7.0)
                game.manager.add(npc)
            created += 1
            game.bus.publish("city", f"远行者带回消息：大陆边缘存在外邦城邦「{name}」",
                             tick=game.clock.total_hours, x=t.x, y=t.y)

    # ---------------- 每小时：建设推进

    def hourly(self, game: "Game") -> None:
        for s in self.settlements:
            if s.building is None:
                continue
            labor = 0.0
            for a in game.manager.alive():
                if a.settlement_id == s.id and a.x == s.x and a.y == s.y:
                    labor += 0.5 + (0.5 if a.profession == "artisan" else 0.0)
            labor *= 1.0 + game.tech.tech_bonus("建造")
            s.building.progress += labor
            if s.building.progress >= DISTRICT_COST:
                s.building.done = True
                s.districts.append(s.building)
                dtype = DISTRICT_TYPES[s.building.type][0]
                game.bus.publish("city", f"「{s.name}」的{dtype}落成！",
                                 tick=game.clock.total_hours, x=s.x, y=s.y)
                s.building = None

    # ---------------- 每日：提议新区域

    def daily(self, game: "Game") -> None:
        self.maybe_found(game)
        for s in self.settlements:
            if s.foreign:
                self._foreign_daily(game, s)
                continue
            if s.building is not None:
                continue
            residents = [a for a in game.manager.alive() if a.settlement_id == s.id]
            if len(residents) < 3:
                continue
            # 统计居民的主导共同需求 → 映射区域类型
            demand: dict[str, int] = {}
            for a in residents:
                dom = a.dominant_need()
                mapping = {"survival": "market", "safety": "industrial",
                           "social": "theater", "esteem": "holy_site",
                           "self_actualization": "academy"}
                demand[mapping[dom]] = demand.get(mapping[dom], 0) + 1
            if not demand:
                continue
            want = max(demand, key=demand.get)
            owned = {d.type for d in s.districts}
            if want not in owned and demand[want] >= max(2, len(residents) // 3):
                s.building = District(type=want)
                dtype = DISTRICT_TYPES[want][0]
                game.bus.publish("city", f"「{s.name}」的居民协作动工，计划修建{dtype}",
                                 tick=game.clock.total_hours, x=s.x, y=s.y)

    def _foreign_daily(self, game: "Game", s: Settlement) -> None:
        """外邦城邦每日群体状态更新：不走 LLM 行动循环，仅维持生计。"""
        residents = [a for a in game.manager.alive() if a.settlement_id == s.id]
        producers = len([a for a in residents
                         if a.profession in ("farmer", "fisher", "hunter")])
        s.food_stock += 0.5 * producers
        for a in residents:
            a.needs["survival"] = min(1.0, a.needs["survival"] + 0.02)
            a.needs["social"] = min(1.0, a.needs["social"] + 0.01)
            a.clamp_needs()

    @staticmethod
    def _reachable_from(game: "Game", sx: int, sy: int) -> set[tuple[int, int]]:
        """从出生点 BFS 出所有可通行连通格，避免城邦落在孤立地块上。"""
        seen: set[tuple[int, int]] = set()
        stack = [(sx, sy)]
        while stack:
            x, y = stack.pop()
            if (x, y) in seen:
                continue
            t = game.world.tile(x, y)
            if t is None or not t.passable:
                continue
            seen.add((x, y))
            stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
        return seen

    def fund(self, game: "Game", settlement: Settlement, district_type: str | None) -> str:
        """玩家 fund：注入神力加速建设或直接立项。"""
        if settlement.building is not None:
            settlement.building.progress += DISTRICT_COST * 0.5
            dtype = DISTRICT_TYPES[settlement.building.type][0]
            return f"神力注入「{settlement.name}」的{dtype}工地，进度大幅推进"
        if district_type and district_type in DISTRICT_TYPES:
            settlement.building = District(type=district_type, progress=DISTRICT_COST * 0.3)
            dtype = DISTRICT_TYPES[district_type][0]
            return f"你降下恩典，「{settlement.name}」开始修建{dtype}"
        return f"「{settlement.name}」当前没有在建区域，请指定区域类型（market/academy/holy_site/industrial/harbor/theater）"

    def describe(self, game: "Game", s: Settlement) -> str:
        flag = "（外邦城邦）" if s.foreign else ""
        lines = [f"定居点「{s.name}」（{s.x},{s.y}）{flag}  建于第{s.founded_day}日"]
        lines.append(f"人口：{self.population(game, s)}  存粮：{s.food_stock:.0f}")
        lines.append(f"区域：{s.district_names()}")
        if s.building:
            pct = min(100, int(s.building.progress / DISTRICT_COST * 100))
            dtype = DISTRICT_TYPES[s.building.type][0]
            filled = pct // 10
            bar = ("█" * filled + ("▓" if pct % 10 >= 5 else "▒") + "░" * max(0, 9 - filled)
                   if pct < 100 else "█" * 10)
            lines.append(f"在建：{dtype} [{bar}] {pct}%")
        return "\n".join(lines)

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {"settlements": [s.to_dict() for s in self.settlements]}

    def load_dict(self, data: dict) -> None:
        self.settlements = [Settlement.from_dict(d) for d in data.get("settlements", [])]
        # 恢复 ID 计数器，避免读档后新建定居点与既有 ID 冲突
        max_id = max((s.id for s in self.settlements), default=0)
        self._next_id = max(self._next_id, max_id + 1)
