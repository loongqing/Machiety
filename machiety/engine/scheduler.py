"""游戏中枢：时间步调度，串联世界、智能体与全部文明子系统。"""

from __future__ import annotations

import random
from typing import Any

from ..agents.agent import Agent
from ..agents.manager import AgentManager
from ..civilization.city import CitySystem
from ..civilization.epoch import EpochSystem
from ..civilization.great_people import GreatPersonSystem
from ..civilization.policy import PolicySystem
from ..civilization.tech import TechSystem
from ..civilization.wonder import WonderSystem
from ..config import GameConfig
from ..llm.base import BaseLLM
from .clock import Clock
from .events import Event, EventBus
from .reaction import COUNCIL_FOCUS, PrayerBoard, ReactionEngine
from .world import World

DISASTER_DURATION = {"flood": 2, "plague": 10, "locust": 3, "drought": 5}
DISASTER_NAMES = {"flood": "洪水", "plague": "瘟疫", "locust": "蝗灾", "drought": "干旱"}
DISASTER_FOCUS = {"flood": "build", "plague": "spirit", "locust": "food", "drought": "food"}
SNAPSHOT_EVERY_DAYS = 7      # 每 7 游戏日自动快照一次


class Game:
    def __init__(self, config: GameConfig, llm: BaseLLM, seed: int | None = None,
                 world_gen: int | None = None) -> None:
        self.config = config
        self.llm = llm
        self.seed = seed if seed is not None else (config.seed or random.SystemRandom().randint(1, 2**31 - 1))
        self.rng = random.Random(self.seed)

        self.bus = EventBus()
        self.clock = Clock()
        # LLM 出错（重试耗尽降级）时提醒玩家：转发到事件总线
        if hasattr(self.llm, "on_error") and self.llm.on_error is None:
            self.llm.on_error = self._notify_llm_error
        self.world = World.generate(config.width, config.height, self.seed,
                                    version=world_gen)
        self.manager = AgentManager(self.rng)
        self.tech = TechSystem(self.rng)
        self.policy = PolicySystem(self.rng)
        self.cities = CitySystem(self.rng)
        self.great = GreatPersonSystem(self.rng)
        self.wonders = WonderSystem()
        self.epoch = EpochSystem()
        self.reaction = ReactionEngine(self.rng)
        self.prayers = PrayerBoard(self.rng)
        self.pending_councils: list[dict] = []   # 待开的灾难应对会议
        self.council_buffs: list[dict] = []      # 会议恢复 buff

        self.active_disasters: list[dict] = []
        self.watched: str | None = None
        self.current_slot: str | None = None    # 正在游玩的存档槽位名
        self.spawn_x, self.spawn_y = self.world.find_spawn(self.rng)

    def _notify_llm_error(self, message: str) -> None:
        """LLM 出错时的提醒：以 system 事件写入事件框。"""
        self.bus.publish("system", message, tick=self.clock.total_hours)

    # ---------------- 开局

    def spawn_settlers(self, n: int | None = None) -> None:
        n = n or self.config.settlers
        sx, sy = self.spawn_x, self.spawn_y
        for _ in range(n):
            x, y = sx, sy
            for _try in range(24):
                tx = sx + self.rng.randint(-3, 3)
                ty = sy + self.rng.randint(-3, 3)
                t = self.world.tile(tx, ty)
                if t and t.passable and not self.manager.agents_at(tx, ty):
                    x, y = tx, ty
                    break
            else:
                # 随机尝试全部落空（出生地周围可通行格不足）：由近及远找空位
                for t in sorted(self.world.tiles_in_radius(sx, sy, 8),
                                key=lambda t: abs(t.x - sx) + abs(t.y - sy)):
                    if t.passable and not self.manager.agents_at(t.x, t.y):
                        x, y = t.x, t.y
                        break
            agent = Agent.spawn(self.manager.new_id(), self.rng, x, y, tick=self.clock.total_hours)
            self.manager.add(agent)
        for t in self.world.tiles_in_radius(sx, sy, 3):
            t.explored = True
        self.policy.assign_factions(self.manager.alive())
        self.cities.spawn_city_states(self, n=2)
        self.bus.publish("founding", f"{n} 名殖民者在({sx},{sy})附近登陆，Machiety 的历史开始了",
                         tick=0, x=sx, y=sy)

    # ---------------- 时间推进

    async def step(self) -> None:
        """推进 1 游戏小时。"""
        self.clock.tick()
        self.cities.hourly(self)
        self._disasters_tick()
        await self.manager.step(self)
        self.reaction.hourly(self)
        await self.policy.war_tick(self)
        if self.clock.is_dusk:
            await self.manager.reflect(self)
        if self.clock.hour == 0:
            await self._daily()

    async def _daily(self) -> None:
        await self.tech.daily(self)
        await self.policy.daily(self)
        self.cities.daily(self)
        await self.prayers.daily(self)
        await self._councils_daily()
        await self.wonders.daily(self)
        await self.epoch.daily(self)
        self._aging_and_vitals()
        self._births()
        self.manager.scatter(self)   # 同格多人散开，保持地图清爽
        await self._check_great_people()
        if self.clock.day % SNAPSHOT_EVERY_DAYS == 0:
            self._auto_snapshot()

    def _auto_snapshot(self) -> None:
        """定期存档：滚动覆盖当前槽位（未命名时用 autosave），避免存档文件膨胀。"""
        try:
            from ..persistence.saver import save_game
            name = self.current_slot or "autosave"
            save_game(self, name)
            self.bus.publish("system", f"历史已被自动铭刻（存档：{name}）",
                             tick=self.clock.total_hours)
        except Exception as e:  # noqa: BLE001
            self.bus.publish("system", f"自动存档失败：{e}",
                             tick=self.clock.total_hours)

    async def skip_days(self, days: int, on_day=None) -> None:
        for d in range(days):
            for _ in range(24):
                await self.step()
            if on_day:
                on_day(d + 1, self)

    # ---------------- 生死

    def _aging_and_vitals(self) -> None:
        new_year = self.clock.day % 360 == 0
        for agent in self.manager.alive():
            if new_year:
                agent.age += 1
            if agent.needs["survival"] <= 0.0:
                self._die(agent, "饥荒")
            elif agent.age >= agent.lifespan and self.rng.random() < 0.04 * (agent.age - agent.lifespan + 1):
                self._die(agent, "寿终")

    def _die(self, agent: Agent, cause: str) -> None:
        agent.alive = False
        agent.cause_of_death = cause
        self.great.on_death(self, agent)
        self.bus.publish("death", f"{agent.name}（{agent.profession_name}）因{cause}离世",
                         tick=self.clock.total_hours, x=agent.x, y=agent.y)
        for other in self.manager.agents_at(agent.x, agent.y):
            if other.id != agent.id:
                other.remember(f"我目睹了 {agent.name} 的死亡（{cause}）",
                               self.clock.total_hours, importance=6.5)
                other.needs["safety"] = max(0.0, other.needs["safety"] - 0.1)

    def _births(self) -> None:
        citizens = [a for a in self.manager.alive() if not a.is_foreign]
        total_food = sum(a.food for a in citizens)
        for s in self.cities.settlements:
            if s.foreign:
                continue
            pop = self.cities.population(self, s)
            if pop >= 2 and s.food_stock + total_food > len(citizens) * 2 \
                    and self.rng.random() < 0.15:
                # 新生儿落在定居点附近空位，避免与居民叠在同一格
                x, y = s.x, s.y
                for nt in sorted(self.world.tiles_in_radius(s.x, s.y, 2),
                                 key=lambda q: abs(q.x - s.x) + abs(q.y - s.y)):
                    if nt.passable and not self.manager.agents_at(nt.x, nt.y):
                        x, y = nt.x, nt.y
                        break
                baby = Agent.spawn(self.manager.new_id(), self.rng, x, y,
                                   tick=self.clock.total_hours)
                baby.age = 14
                baby.memory.observations.clear()
                baby.memory.core.clear()
                baby.memory.add(f"我在{s.name}长大，听着前辈们的故事走向自己的人生。",
                                tick=self.clock.total_hours, importance=8.0)
                baby.settlement_id = s.id
                self.manager.add(baby)
                self.policy.assign_factions([baby])
                self.bus.publish("birth", f"新成员 {baby.name} 在「{s.name}」加入了社群",
                                 tick=self.clock.total_hours, x=s.x, y=s.y)

    async def _check_great_people(self) -> None:
        candidates = [a for a in self.manager.alive()
                      if a.influence + a.honor >= 15 and not a.great_title
                      and a.achievement >= 1]
        for agent in candidates[:2]:
            await self.great.check(self, agent)

    # ---------------- 灾难

    def unleash_disaster(self, dtype: str, x: int, y: int) -> str:
        name = DISASTER_NAMES.get(dtype, dtype)
        self.active_disasters.append(
            {"type": dtype, "x": x, "y": y, "days_left": DISASTER_DURATION.get(dtype, 3)})
        for t in self.world.tiles_in_radius(x, y, 3):
            t.disaster = dtype
        s = self.cities.nearest(x, y, radius=5)
        if s and not s.foreign:
            self.pending_councils.append(
                {"settlement_id": s.id, "dtype": dtype, "day": self.clock.day})
        self.bus.publish("disaster", f"天降{name}！（{x},{y}）大地为之变色",
                         tick=self.clock.total_hours, x=x, y=y)
        return f"{name}已降临于（{x},{y}），持续约{DISASTER_DURATION.get(dtype, 3)}日"

    def _disasters_tick(self) -> None:
        if not self.active_disasters:
            return
        if self.clock.hour != 12:      # 每日正午结算一次
            return
        ended = []
        for d in self.active_disasters:
            dtype, x, y = d["type"], d["x"], d["y"]
            if dtype == "plague":
                for a in self.manager.alive():
                    if abs(a.x - x) + abs(a.y - y) <= 5:
                        if self.rng.random() < 0.25:
                            a.needs["survival"] -= 0.25
                            a.clamp_needs()
                        if a.needs["survival"] <= 0.05 and self.rng.random() < 0.3:
                            self._die(a, "瘟疫")
                self.tech.add_inspiration("spirit", 1.0)
            elif dtype == "locust":
                for t in self.world.tiles_in_radius(x, y, 4):
                    if t.resource == "grain":
                        t.resource_amount = max(0, t.resource_amount - t.resource_amount // 2)
                for s in self.cities.settlements:
                    if abs(s.x - x) + abs(s.y - y) <= 5:
                        s.food_stock *= 0.6
                self.tech.add_inspiration("food", 3.0)
            elif dtype == "flood":
                for s in self.cities.settlements:
                    if abs(s.x - x) + abs(s.y - y) <= 4:
                        s.food_stock *= 0.7
                        if s.building:
                            s.building.progress *= 0.6
                for t in self.world.tiles_in_radius(x, y, 4):
                    if t.resource == "grain":
                        t.resource_amount = max(0, t.resource_amount - t.resource_amount // 2)
                self.tech.add_inspiration("food", 2.0)
                self.tech.add_inspiration("build", 1.5)
            elif dtype == "drought":
                for t in self.world.tiles_in_radius(x, y, 4):
                    if t.resource == "grain":
                        t.resource_amount -= max(1, int(t.resource_amount * 0.3))
                        t.resource_amount = max(0, t.resource_amount)
                for s in self.cities.settlements:
                    if abs(s.x - x) + abs(s.y - y) <= 5:
                        s.food_stock *= 0.85
                for a in self.manager.alive():
                    if abs(a.x - x) + abs(a.y - y) <= 5:
                        a.needs["survival"] -= 0.05
                        a.clamp_needs()
                self.tech.add_inspiration("food", 2.5)
            d["days_left"] -= 1
            if d["days_left"] <= 0:
                ended.append(d)
        for d in ended:
            self.active_disasters.remove(d)
            for t in self.world.tiles_in_radius(d["x"], d["y"], 3):
                if t.disaster == d["type"]:
                    t.disaster = None
            self.bus.publish("disaster", f"{DISASTER_NAMES.get(d['type'], '灾难')}已消退",
                             tick=self.clock.total_hours, x=d["x"], y=d["y"])

    # ---------------- 灾难应对会议

    async def _councils_daily(self) -> None:
        tick = self.clock.total_hours
        # 先结算既有恢复 buff
        for buff in list(self.council_buffs):
            s = next((x for x in self.cities.settlements
                      if x.id == buff["settlement_id"]), None)
            if s is not None:
                self._apply_council_buff(s, buff["focus"])
            buff["days_left"] -= 1
            if buff["days_left"] <= 0:
                self.council_buffs.remove(buff)
        # 再召开新会议
        for c in list(self.pending_councils):
            self.pending_councils.remove(c)
            s = next((x for x in self.cities.settlements
                      if x.id == c["settlement_id"]), None)
            if s is None or s.foreign:
                continue
            members = [a for a in self.manager.alive() if a.settlement_id == s.id]
            if not members:
                continue
            leader = max(members, key=lambda a: a.influence)
            focus = DISASTER_FOCUS.get(c["dtype"], "food")
            if self.config.llm.economy:
                strategy = f"{leader.name} 召集众人按老办法重建家园"
            else:
                result = await self.llm.generate("council", {
                    "settlement": s.name,
                    "disaster": DISASTER_NAMES.get(c["dtype"], c["dtype"]),
                    "leader": leader.name, "food_stock": round(s.food_stock, 1),
                    "population": len(members), "suggested_focus": focus,
                    "tier": "large"})
                focus = result.get("focus") if result.get("focus") in COUNCIL_FOCUS else focus
                strategy = result.get("strategy") or f"{leader.name} 带领众人应对灾难"
            self.council_buffs.append({"settlement_id": s.id, "focus": focus, "days_left": 3})
            self.bus.publish("council",
                             f"「{s.name}」召开灾难应对会议，{leader.name} 提议：{strategy}",
                             tick=tick, x=s.x, y=s.y)

    def _apply_council_buff(self, s, focus: str) -> None:
        members = [a for a in self.manager.alive() if a.settlement_id == s.id]
        if focus == "food":
            s.food_stock += 2
        elif focus == "build" and s.building:
            s.building.progress += 3
        elif focus == "spirit":
            for a in members:
                a.needs["safety"] += 0.05
                a.needs["social"] += 0.05
                a.clamp_needs()
            self.policy.unrest = max(0.0, self.policy.unrest - 3.0)
        elif focus == "safety":
            for a in members:
                a.needs["safety"] += 0.08
                a.clamp_needs()

    # ---------------- 观察与统计

    def stats(self) -> dict[str, Any]:
        alive = self.manager.alive()
        food_stock = sum(s.food_stock for s in self.cities.settlements)
        return {
            "population": len(alive),
            "food_stock": round(food_stock, 1),
            "wealth": sum(a.wealth for a in alive),
            "techs": len(self.tech.techs),
            "settlements": len(self.cities.settlements),
            "era": self.epoch.era,
            "day": self.clock.day,
        }

    def status_line(self) -> str:
        st = self.stats()
        return (f"纪元{self.clock.year}年{self.clock.day_of_year}日{self.clock.hour:02d}时 | "
                f"{st['era']}时代 | 人口{st['population']} | "
                f"{self.policy.spirit()}")

    # ---------------- 序列化

    def to_save_dict(self) -> dict:
        return {
            "meta": {"seed": self.seed, "width": self.world.width,
                     "height": self.world.height, "version": 1,
                     "world_gen": World.WORLD_GEN_VERSION,
                     "spawn_x": self.spawn_x, "spawn_y": self.spawn_y},
            "clock": self.clock.to_dict(),
            "world_dynamic": self.world.dynamic_state(),
            "agents": [a.to_dict() for a in self.manager.agents],
            "tech": self.tech.to_dict(),
            "policy": self.policy.to_dict(),
            "cities": self.cities.to_dict(),
            "great": self.great.to_dict(),
            "wonders": self.wonders.to_dict(),
            "epoch": self.epoch.to_dict(),
            "disasters": self.active_disasters,
            "watched": self.watched,
            "reaction": self.reaction.to_dict(),
            "prayers": self.prayers.to_dict(),
            "pending_councils": self.pending_councils,
            "council_buffs": self.council_buffs,
            "chronicle": [e.to_dict() for e in self.bus.chronicle],
        }

    @classmethod
    def from_save_dict(cls, config: GameConfig, llm: BaseLLM, data: dict) -> "Game":
        meta = data["meta"]
        # 旧档缺省 world_gen=1：用 v1 算法重建地貌，保证旧档地貌不变
        game = cls(config, llm, seed=int(meta["seed"]),
                   world_gen=int(meta.get("world_gen", 1)))
        game.clock = Clock.from_dict(data["clock"])
        game.world.apply_dynamic_state(data.get("world_dynamic", []))
        # 恢复出生点坐标（兼容旧档无此字段）
        if "spawn_x" in meta:
            game.spawn_x = int(meta["spawn_x"])
            game.spawn_y = int(meta["spawn_y"])
        for agent_data in data.get("agents", []):
            game.manager.add(Agent.from_dict(agent_data))
        game.tech.load_dict(data.get("tech", {}))
        game.policy.load_dict(data.get("policy", {}))
        game.cities.load_dict(data.get("cities", {}))
        game.great.load_dict(data.get("great", {}))
        game.wonders.load_dict(data.get("wonders", {}))
        game.epoch.load_dict(data.get("epoch", {}))
        game.active_disasters = list(data.get("disasters", []))
        game.watched = data.get("watched")
        game.reaction.load_dict(data.get("reaction", {}))
        game.prayers.load_dict(data.get("prayers", {}))
        game.pending_councils = list(data.get("pending_councils", []))
        game.council_buffs = list(data.get("council_buffs", []))
        game.bus.chronicle = [Event.from_dict(e) for e in data.get("chronicle", [])]
        # 恢复最近事件到日志队列，供 UI 侧栏显示
        for e in game.bus.chronicle[-20:]:
            game.bus.log.append(e)
        return game
