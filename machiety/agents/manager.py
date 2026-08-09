"""智能体管理器：每时间步并行决策、批量对话、执行互动、夜间反思。"""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

from .agent import Agent, NEED_NAMES

if TYPE_CHECKING:
    from ..engine.scheduler import Game

DIRECTIONS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}


class AgentManager:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.agents: list[Agent] = []
        self._next_id = 1

    # ---------------- 集合操作

    def add(self, agent: Agent) -> None:
        self.agents.append(agent)
        self._next_id = max(self._next_id, agent.id + 1)

    def new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def alive(self) -> list[Agent]:
        return [a for a in self.agents if a.alive]

    def by_name(self, name: str) -> Agent | None:
        return next((a for a in self.agents if a.name == name and a.alive), None)

    def agents_at(self, x: int, y: int) -> list[Agent]:
        return [a for a in self.alive() if a.x == x and a.y == y]

    def scatter(self, game: "Game", max_per_tile: int = 1) -> int:
        """把同一格多余的角色移到附近空位（外邦城邦、读档旧世界兜底），返回移动数。"""
        from collections import defaultdict

        by_pos: dict[tuple[int, int], list[Agent]] = defaultdict(list)
        for a in self.alive():
            by_pos[(a.x, a.y)].append(a)
        occupied = set(by_pos)
        moved = 0
        for pos, group in sorted(by_pos.items(), key=lambda kv: -len(kv[1])):
            if len(group) <= max_per_tile:
                continue
            nearby = sorted(game.world.tiles_in_radius(pos[0], pos[1], 3),
                            key=lambda t: abs(t.x - pos[0]) + abs(t.y - pos[1]))
            for a in group[max_per_tile:]:
                spot = next((t for t in nearby
                             if t.passable and (t.x, t.y) not in occupied), None)
                if spot is None:
                    break
                a.prev_x, a.prev_y = a.x, a.y
                a.x, a.y = spot.x, spot.y
                occupied.add((spot.x, spot.y))
                moved += 1
        return moved

    # ---------------- 每小时行动循环

    async def step(self, game: "Game") -> None:
        # 外邦城邦 NPC 不跑 LLM 行动循环（由 cities._foreign_daily 群体更新）
        agents = [a for a in self.alive() if not a.is_foreign]
        if not agents:
            return
        self._decay_needs(agents)
        if game.clock.is_dawn:
            self._dawn_rebalance(agents)
        if game.clock.hour in (8, 19):
            self._meal(game, agents)

        # 1) 感知 + LLM 并行规划
        plans = await asyncio.gather(*(self._plan(game, a) for a in agents))

        # 2) 执行（对话按地块批量生成）
        talk_groups: dict[tuple[int, int], list[Agent]] = {}
        for agent, plan in zip(agents, plans):
            action = plan.get("action", "rest")
            if action == "talk":
                talk_groups.setdefault((agent.x, agent.y), []).append(agent)
                continue
            await self._execute(game, agent, plan)

        for (x, y), group in talk_groups.items():
            if len(group) >= 2:
                await self._group_talk(game, group)
            else:
                await self._execute(game, group[0], {"action": "rest", "reason": "无人可谈"})

        # 3) 资源争夺冲突
        await self._conflicts(game)

    # ---------------- 需求与进食

    def _decay_needs(self, agents: list[Agent]) -> None:
        for a in agents:
            a.needs["survival"] -= 0.012
            a.needs["safety"] -= 0.004
            a.needs["social"] -= 0.008
            a.needs["esteem"] -= 0.003
            a.needs["self_actualization"] -= 0.002
            a.clamp_needs()

    def _dawn_rebalance(self, agents: list[Agent]) -> None:
        """黎明：一夜休整后更新需求优先级，安全与社交小幅恢复。"""
        for a in agents:
            a.needs["safety"] = min(1.0, a.needs["safety"] + 0.06)
            a.needs["social"] = min(1.0, a.needs["social"] + 0.03)
            a.needs["self_actualization"] = min(1.0, a.needs["self_actualization"] + 0.02)
            a.clamp_needs()

    def _meal(self, game: "Game", agents: list[Agent]) -> None:
        for a in agents:
            eaten = False
            if a.food > 0:
                a.inventory["food"] -= 1
                eaten = True
            else:
                s = game.cities.nearest(a.x, a.y, radius=4)
                if s and s.food_stock >= 1:
                    s.food_stock -= 1
                    eaten = True
            if eaten:
                a.needs["survival"] = min(1.0, a.needs["survival"] + 0.25)
            else:
                a.needs["survival"] -= 0.15
                a.remember("我饿着肚子，饥荒的阴影笼罩着我", game.clock.total_hours, importance=5.0)
                game.tech.add_inspiration("food", 1.0)
            a.clamp_needs()

    # ---------------- 规划

    async def _plan(self, game: "Game", agent: Agent) -> dict:
        tile = game.world.tile(agent.x, agent.y)
        settlement = game.cities.nearest(agent.x, agent.y, radius=3)
        nearby = [o.name for o in self.agents_at(agent.x, agent.y) if o.id != agent.id]

        dom_need = agent.dominant_need()
        # 节流模式：主导需求与记忆数均未变化且 6 tick 内规划过 → 复用缓存
        if game.config.llm.economy:
            cache = agent._plan_cache
            if (cache.get("plan") is not None
                    and cache.get("dom_need") == dom_need
                    and cache.get("mem_count") == len(agent.memory.observations)
                    and game.clock.total_hours - cache.get("tick", -10 ** 6) < 6):
                return cache["plan"]
        query = NEED_NAMES.get(dom_need, "") + " " + " ".join(agent.goals)
        memories = [m.text for m in agent.memory.retrieve(query, game.clock.total_hours, k=3)]

        payload = {
            "agent": {
                "name": agent.name, "profession": agent.profession,
                "needs": {k: round(v, 2) for k, v in agent.needs.items()},
                "goals": agent.goals, "food": agent.food,
                "personality": agent.personality.describe(),
            },
            "place": {
                "terrain": tile.terrain if tile else "plain",
                "resource": tile.resource if tile else None,
                "resource_amount": tile.resource_amount if tile else 0,
                "food_resource": bool(tile and tile.food_resource),
                "settlement": settlement.name if settlement else None,
            },
            "nearby": nearby[:5],
            "memories": memories,
            "hour": game.clock.hour,
            "is_night": game.clock.is_night,
            "tier": "small",
        }
        plan = await game.llm.generate("plan", payload)
        if game.config.llm.economy:
            agent._plan_cache = {
                "plan": plan, "dom_need": dom_need,
                "mem_count": len(agent.memory.observations),
                "tick": game.clock.total_hours,
            }
        return plan

    # ---------------- 执行

    async def _execute(self, game: "Game", agent: Agent, plan: dict) -> None:
        action = plan.get("action", "rest")
        tick = game.clock.total_hours

        if action in ("move", "explore", "patrol"):
            self._move(game, agent, plan.get("direction") or self.rng.choice("nsew"),
                       explore=action == "explore")
        elif action == "gather":
            self._gather(game, agent)
        elif action == "build":
            self._build(game, agent)
        elif action == "worship":
            agent.needs["self_actualization"] += 0.08
            agent.needs["social"] += 0.03
            agent.clamp_needs()
            game.tech.add_inspiration("spirit", 0.3)
            if self.rng.random() < 0.02 * (1.0 + game.policy.bonus("culture")
                                           + game.great.gift_bonus(game, "culture")):
                game.epoch.cultural_events += 1
                game.bus.publish("culture", f"{agent.name} 主持了一场庄严的仪式，观者动容",
                                 tick=tick, x=agent.x, y=agent.y)
        elif action == "research":
            cat = self.rng.choice(["food", "war", "spirit", "economy", "build"])
            gain = 0.3 * (1.0 + game.wonders.bonuses.get("research_bonus", 0.0)
                          + game.policy.bonus("research")
                          + game.great.gift_bonus(game, "research"))
            game.tech.add_inspiration(cat, gain)
            agent.needs["esteem"] += 0.02
            agent.clamp_needs()
        elif action == "trade":
            self._trade(game, agent, plan.get("target", ""))
        else:  # rest 或其他
            agent.needs["survival"] += 0.02
            agent.needs["safety"] += 0.04 if game.clock.is_night else 0.02
            agent.clamp_needs()

    def _move(self, game: "Game", agent: Agent, direction: str, explore: bool = False) -> None:
        # 优先走指定方向；若该格不可通行或已有人，按 n/s/e/w 顺序换向
        order = [direction] + [d for d in "nsew" if d != direction]
        target = None
        for d in order:
            dx, dy = DIRECTIONS[d]
            t = game.world.tile(agent.x + dx, agent.y + dy)
            if t is None or not t.passable or self.agents_at(t.x, t.y):
                continue
            target = t
            break
        if target is None:
            return
        agent.prev_x, agent.prev_y = agent.x, agent.y
        agent.x, agent.y = target.x, target.y
        # 探索迷雾（explore_bonus 奇观加成扩大视野）
        radius = 2 if game.wonders.bonuses.get("explore_bonus", 0) > 0 else 1
        for t in game.world.tiles_in_radius(agent.x, agent.y, radius):
            if not t.explored:
                t.explored = True
                if explore:
                    agent.remember(f"我探索了({t.x},{t.y})的未知之地",
                                   game.clock.total_hours, importance=3.0)

    def _gather(self, game: "Game", agent: Agent) -> None:
        tile = game.world.tile(agent.x, agent.y)
        if tile is None:
            return
        tick = game.clock.total_hours
        bonus = 1.0 + game.tech.tech_bonus("粮") + game.wonders.bonuses.get("food_bonus", 0.0) \
            + game.policy.bonus("food") + game.great.gift_bonus(game, "food")
        if tile.resource and tile.resource_amount > 0:
            if tile.food_resource:
                amt = int(2 * bonus)
                if (agent.profession == "farmer" and tile.resource == "grain") or \
                   (agent.profession == "fisher" and tile.resource == "fish"):
                    amt += 1
                amt = min(amt, tile.resource_amount)
                tile.resource_amount -= amt
                agent.inventory["food"] = agent.inventory.get("food", 0) + amt
                s = game.cities.nearest(agent.x, agent.y, radius=3)
                if s:
                    s.food_stock += amt * 0.5
                agent.needs["survival"] += 0.05
            elif tile.resource == "wood":
                amt = min(2, tile.resource_amount)
                tile.resource_amount -= amt
                agent.wealth += 1
                s = game.cities.nearest(agent.x, agent.y, radius=3)
                if s and s.building:
                    s.building.progress += 2
            else:  # iron / horse / luxury
                tile.resource_amount -= 1
                agent.wealth += 2 if tile.resource == "luxury" else 1
            agent.clamp_needs()
        else:
            if self.rng.random() < 0.22:
                agent.inventory["food"] = agent.inventory.get("food", 0) + 1
            else:
                agent.remember("我寻觅许久却一无所获", tick, importance=2.5)
                if agent.needs["survival"] < 0.4:
                    game.tech.add_inspiration("food", 0.8)

    def _build(self, game: "Game", agent: Agent) -> None:
        s = game.cities.nearest(agent.x, agent.y, radius=3)
        if s and s.building:
            labor = 1.5 if agent.profession == "artisan" else 0.8
            s.building.progress += labor * (1.0 + game.tech.tech_bonus("建"))
        agent.needs["safety"] += 0.04
        agent.clamp_needs()

    def _trade(self, game: "Game", agent: Agent, target_name: str) -> None:
        partner = next((o for o in self.agents_at(agent.x, agent.y)
                        if o.name == target_name and o.alive), None)
        if partner is None:
            return
        # 以粮易财或以财易粮
        if agent.food >= 2 and partner.wealth >= 1:
            agent.inventory["food"] -= 2
            agent.wealth += 1
            partner.wealth -= 1
            partner.inventory["food"] = partner.inventory.get("food", 0) + 2
        elif agent.wealth >= 1 and partner.food >= 2:
            agent.wealth -= 1
            agent.inventory["food"] = agent.inventory.get("food", 0) + 2
            partner.inventory["food"] -= 2
            partner.wealth += 1
        else:
            return
        if game.wonders.bonuses.get("trade_bonus", 0) > 0:
            agent.wealth += 1      # 商路奇观：交易额外获利
        if game.policy.bonus("wealth") > 0:
            agent.wealth += 1      # 经济政策：商贸获利
        if game.great.gift_bonus(game, "wealth") > 0:
            agent.wealth += 1      # 伟人天赋：商路财富
        for p in (agent, partner):
            p.needs["social"] += 0.08
            p.needs["esteem"] += 0.03
            p.clamp_needs()
        game.tech.add_inspiration("economy", 0.4)

    # ---------------- 批量对话

    async def _group_talk(self, game: "Game", group: list[Agent]) -> None:
        result = await game.llm.generate("talk", {
            "agents": [a.name for a in group],
            "place": f"({group[0].x},{group[0].y})",
            "tier": "small",
        })
        summary = result.get("summary", "众人闲谈了一阵")
        tick = game.clock.total_hours
        for a in group:
            a.needs["social"] += 0.15
            a.needs["esteem"] += 0.02
            a.clamp_needs()
            a.remember(summary, tick, importance=3.0)
        for pair in result.get("deltas", []):
            if len(pair) == 3:
                na, nb, delta = pair[0], pair[1], int(pair[2])
                aa, ab = self.by_name(na), self.by_name(nb)
                if aa:
                    aa.relations[nb] = aa.relations.get(nb, 0) + delta
                if ab:
                    ab.relations[na] = ab.relations.get(na, 0) + delta

    # ---------------- 冲突

    async def _conflicts(self, game: "Game") -> None:
        from ..engine.conflict import resolve_conflict
        agents = self.alive()
        for i, a in enumerate(agents):
            for b in agents[i + 1:]:
                # 同格或相邻格才可能爆发冲突（角色不再堆叠，扩展为相邻判定）
                if abs(a.x - b.x) + abs(a.y - b.y) > 1:
                    continue
                if a.personality.agreeableness > 0.8 \
                        or b.personality.agreeableness > 0.8:
                    continue
                feud = a.relations.get(b.name, 0) <= -5 or b.relations.get(a.name, 0) <= -5
                tile = game.world.tile(b.x, b.y)
                scarce = tile is not None and tile.resource and 0 < tile.resource_amount <= 3
                if not scarce and not feud:
                    continue
                reason = "积怨爆发" if feud else f"{tile.resource}资源争夺"
                await resolve_conflict(game, a, b, reason)
                return  # 每步最多一场冲突，避免连锁

    # ---------------- 夜间反思

    async def reflect(self, game: "Game") -> None:
        day_start = game.clock.day * 24
        targets = [a for a in self.alive() if len(a.memory.day_events(day_start)) >= 2]
        if not targets:
            return
        if game.config.llm.economy:
            # 节流模式：按 5 人分组，每组只调 1 次反思
            for i in range(0, len(targets), 5):
                group = targets[i:i + 5]
                events = [ev for a in group
                          for ev in a.memory.day_events(day_start)[:2]][:8]
                result = await game.llm.generate("reflect", {
                    "name": "、".join(a.name for a in group),
                    "day_events": events, "tier": "small",
                })
                summary = result.get("summary") or "众人度过了寻常的一天"
                for agent in group:
                    agent.memory.add_summary(f"（群体回忆）{summary}",
                                             game.clock.total_hours)
            return
        tasks = []
        for a in targets:
            tasks.append(game.llm.generate("reflect", {
                "name": a.name, "day_events": a.memory.day_events(day_start)[:6],
                "tier": "small",
            }))
        results = await asyncio.gather(*tasks)
        for agent, result in zip(targets, results):
            summary = result.get("summary") or f"{agent.name} 度过了寻常的一天"
            agent.memory.add_summary(summary, game.clock.total_hours)
            agent.mood = result.get("mood", agent.mood)
            new_goal = result.get("new_goal")
            if new_goal and new_goal not in agent.goals:
                agent.goals.append(new_goal)
                if len(agent.goals) > 3:
                    agent.goals.pop(0)
