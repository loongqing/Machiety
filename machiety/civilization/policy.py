"""动态政策卡：派系提案 → 议会投票 → 四槽位生效；玩家可 decree 强行颁布。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.scheduler import Game

SLOTS = ["military", "economy", "diplomacy", "culture"]
SLOT_NAMES = {"military": "军事", "economy": "经济", "diplomacy": "外交", "culture": "文化"}

# 政策效果种类：由 LLM（议会提案）或条文关键词（神谕 decree）裁定，落地为数值加成
POLICY_EFFECTS = {
    "food": "粮食增产", "wealth": "商贸繁荣", "research": "学术昌盛",
    "culture": "文化繁荣", "war": "军力强盛", "stability": "社会安定",
}

FACTION_NAMES = ["商人行会", "军人集团", "祭司团", "学者会", "农民议会"]
FACTION_PROFESSIONS = {
    "商人行会": ["merchant"],
    "军人集团": ["soldier"],
    "祭司团": ["priest"],
    "学者会": ["scholar"],
    "农民议会": ["farmer", "hunter", "fisher"],
}


@dataclass
class Policy:
    name: str
    slot: str
    description: str
    proposer: str
    day: int
    by_decree: bool = False
    effect: str = ""              # POLICY_EFFECTS 之一，空表示暂无裁定的效果

    def to_dict(self) -> dict:
        return {"name": self.name, "slot": self.slot, "description": self.description,
                "proposer": self.proposer, "day": self.day, "by_decree": self.by_decree,
                "effect": self.effect}

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        return cls(name=d["name"], slot=d["slot"], description=d["description"],
                   proposer=d["proposer"], day=int(d["day"]), by_decree=bool(d.get("by_decree")),
                   effect=d.get("effect", ""))


@dataclass
class Faction:
    name: str
    support: float = 60.0       # 0~100 对当前政权的支持度

    def to_dict(self) -> dict:
        return {"name": self.name, "support": round(self.support, 1)}

    @classmethod
    def from_dict(cls, d: dict) -> "Faction":
        return cls(name=d["name"], support=float(d["support"]))


class PolicySystem:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.factions: list[Faction] = [Faction(n) for n in FACTION_NAMES]
        self.active: dict[str, Policy | None] = {s: None for s in SLOTS}
        self.history: list[Policy] = []
        self.unrest: float = 0.0      # 动荡值，过高触发叛乱事件
        self.war_target_id: int | None = None   # 宣战目标城邦（settlement id）

    def faction(self, name: str) -> Faction | None:
        return next((f for f in self.factions if f.name == name), None)

    def slot_name(self, slot: str) -> str:
        return SLOT_NAMES.get(slot, slot)

    def bonus(self, kind: str) -> float:
        """生效政策对某类活动的累计加成：每项匹配效果的政策 +0.2。"""
        return sum(0.2 for p in self.active.values() if p and p.effect == kind)

    @staticmethod
    def _decree_effect(text: str) -> str:
        """神谕 decree 无 LLM 参与，按条文关键词裁定效果方向。"""
        if any(k in text for k in ("军", "战", "兵", "征", "武")):
            return "war"
        if any(k in text for k in ("粮", "农", "田", "食", "灌溉")):
            return "food"
        if any(k in text for k in ("学", "教", "书", "知识", "研究")):
            return "research"
        if any(k in text for k in ("文", "艺", "乐", "祭", "信仰")):
            return "culture"
        if any(k in text for k in ("商", "市", "贸", "税", "钱", "自由")):
            return "wealth"
        return "stability"

    # ---------------- 玩家 decree

    def decree(self, game: "Game", text: str) -> str:
        """强行颁布政策：自动归入空槽位，引发部分派系不满。"""
        slot = next((s for s in SLOTS if self.active[s] is None), None) or "economy"
        effect = self._decree_effect(text)
        policy = Policy(name=text[:20], slot=slot, description=text,
                        proposer="神谕", day=game.clock.day, by_decree=True, effect=effect)
        replaced = self.active[slot]
        self.active[slot] = policy
        self.history.append(policy)
        # 与神谕利益相悖的派系好感下降，动荡累积
        hurt = self.rng.sample(self.factions, k=self.rng.randint(1, 2))
        for f in hurt:
            f.support = max(0.0, f.support - self.rng.uniform(8, 18))
        self.unrest += 12.0
        msg = (f"神谕降临，政策「{policy.name}」已颁布至[{self.slot_name(slot)}]槽位，"
               f"生效「{POLICY_EFFECTS.get(effect, '暂无')}」")
        if replaced:
            msg += f"（原政策「{replaced.name}」被废除）"
        msg += "。" + "、".join(f.name for f in hurt) + " 对此颇有微词"
        self._check_rebellion(game)
        # 宣战关键词：向外邦城邦开战，军人即刻行军
        if any(k in text for k in ("宣战", "进攻", "讨伐")):
            foreign = [s for s in game.cities.settlements if s.foreign]
            if foreign:
                target = foreign[0]
                self.war_target_id = target.id
                game.bus.publish("policy",
                                 f"战云密布：神谕向外邦城邦「{target.name}」宣战，军队开拔",
                                 tick=game.clock.total_hours, x=target.x, y=target.y)
                msg += f"。对外邦城邦「{target.name}」的宣战令已下达，军人将行军讨伐"
            else:
                msg += "。然四海之内已无敌国外邦"
        return msg

    def _check_rebellion(self, game: "Game") -> None:
        if self.unrest >= 60.0 and self.rng.random() < 0.4:
            self.unrest = 0.0
            angry = min(self.factions, key=lambda f: f.support)
            soldiers = [a for a in game.manager.alive() if a.profession == "soldier"]
            if soldiers:
                rebel = self.rng.choice(soldiers)
                rebel.needs["safety"] = max(0.0, rebel.needs["safety"] - 0.3)
                game.bus.publish("rebellion",
                                 f"{angry.name} 煽动叛乱！士兵 {rebel.name} 在街头鼓动人心，局势动荡",
                                 tick=game.clock.total_hours, x=rebel.x, y=rebel.y)
            else:
                game.bus.publish("rebellion", f"{angry.name} 煽动叛乱！街头人心浮动",
                                 tick=game.clock.total_hours)

    # ---------------- 战争：行军与裁决

    async def war_tick(self, game: "Game") -> None:
        """战争状态每小时推进：军人沿曼哈顿方向行军，抵达后按人数与士气裁决。"""
        if self.war_target_id is None:
            return
        target = next((s for s in game.cities.settlements
                       if s.id == self.war_target_id), None)
        if target is None or not target.foreign:
            self.war_target_id = None
            return
        soldiers = [a for a in game.manager.alive()
                    if a.profession == "soldier" and not a.is_foreign]
        tick = game.clock.total_hours
        if not soldiers:
            self.war_target_id = None
            game.bus.publish("policy", "国中已无军人，这场战争无疾而终", tick=tick)
            return
        # 行军：每人每小时迈向目标（四方向择优，绕开不可通行地形）
        arrived = []
        for a in soldiers:
            if abs(a.x - target.x) + abs(a.y - target.y) <= 1:
                arrived.append(a)
                continue
            d0 = abs(a.x - target.x) + abs(a.y - target.y)
            best_t, best_d = None, d0
            fallback_t, fallback_d = None, None
            for mx, my in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                t = game.world.tile(a.x + mx, a.y + my)
                if not t or not t.passable:
                    continue
                d = abs(t.x - target.x) + abs(t.y - target.y)
                if d < best_d:
                    best_t, best_d = t, d
                # fallback 兜底绕行时禁止退回上一格，避免原地震荡
                if (t.x, t.y) != (a.prev_x, a.prev_y):
                    if fallback_d is None or d < fallback_d:
                        fallback_t, fallback_d = t, d
            step_t = best_t or fallback_t
            if step_t is not None:
                a.prev_x, a.prev_y = a.x, a.y
                a.x, a.y = step_t.x, step_t.y
            if abs(a.x - target.x) + abs(a.y - target.y) <= 1:
                arrived.append(a)
        if not arrived:
            return
        # 抵达城下：人数 × 士气（安全需求）对阵守军，军事政策强化攻势
        morale = sum(a.needs["safety"] for a in soldiers) / len(soldiers)
        attack = len(soldiers) * (0.5 + morale) * (1.0 + self.bonus("war")
                                                   + game.great.gift_bonus(game, "war"))
        defenders = [a for a in game.manager.alive()
                     if a.settlement_id == target.id and a.is_foreign]
        defense = len(defenders) * 0.8 + 1.0
        result = await game.llm.generate("adjudicate", {
            "a": {"name": "国军", "influence": attack},
            "b": {"name": f"城邦「{target.name}」", "influence": defense},
            "context": "攻城战", "tier": "large",
        })
        win = result.get("winner") == "国军" or (
            result.get("winner") not in ("国军", f"城邦「{target.name}」") and attack > defense)
        if win:
            target.foreign = False
            self.war_target_id = None
            for a in defenders:
                a.is_foreign = False
                a.remember(f"城邦「{target.name}」被兼并，我成为了这个国家的一员",
                           tick, importance=8.0)
                if "与新同胞和睦共处" not in a.goals:
                    a.goals.append("与新同胞和睦共处")
            for a in soldiers:
                a.honor += 5.0
                a.achievement += 1
                a.remember(f"我随军征服了「{target.name}」，凯旋而归", tick, importance=7.5)
            game.bus.publish("city", f"大军击败外邦城邦「{target.name}」，将其并入版图",
                             tick=tick, x=target.x, y=target.y)
        else:
            self.war_target_id = None
            for a in soldiers:
                a.needs["safety"] = max(0.0, a.needs["safety"] - 0.2)
                a.remember(f"进攻「{target.name}」失利，我黯然撤军", tick, importance=7.0)
            game.bus.publish("policy", f"大军在「{target.name}」城下折戟，这场战争以失败告终",
                             tick=tick, x=target.x, y=target.y)

    # ---------------- 每日：提案与投票

    async def daily(self, game: "Game") -> None:
        self.unrest = max(0.0, self.unrest - 2.0 * (1.0 + self.bonus("stability")
                                                    + game.great.gift_bonus(game, "stability")))
        # 外交槽生效：结盟/通商政策每日给双方小额财富与粮食加成
        if self.active.get("diplomacy") is not None:
            for s in game.cities.settlements:
                s.food_stock += 0.5 if s.foreign else 0.3
            for a in game.manager.alive():
                if a.profession == "merchant":
                    a.wealth += 1
        empty_slots = [s for s in SLOTS if self.active[s] is None]
        if not empty_slots or self.rng.random() > 0.35:
            return
        faction = self.rng.choice(self.factions)
        result = await game.llm.generate("policy_proposal",
                                         {"faction": faction.name, "tier": "large"})
        name = result.get("name") or f"{faction.name}法案"
        active_names = {p.name for p in self.active.values() if p}
        if name in active_names:
            return  # 同类政策已生效，不再重复提案
        slot = result.get("slot") if result.get("slot") in empty_slots else empty_slots[0]
        raw_effect = result.get("effect")
        effect = raw_effect if raw_effect in POLICY_EFFECTS else ""
        policy = Policy(name=name, slot=slot,
                        description=result.get("description", "一项新政策"),
                        proposer=faction.name, day=game.clock.day, effect=effect)
        # 议会辩论：反对派系的驳辞可能左右票数（节流模式跳过）
        swing = 0
        if not game.config.llm.economy:
            others = [f for f in self.factions if f.name != faction.name]
            opp = self.rng.choice(others)
            result = await game.llm.generate("debate", {
                "policy": {"name": name, "slot": slot,
                           "description": policy.description, "proposer": faction.name},
                "opponent": opp.name, "tier": "large"})
            try:
                swing = max(-10, min(10, int(result.get("swing", 0))))
            except (TypeError, ValueError):
                swing = 0
            game.bus.publish("policy",
                             f"议会辩论「{name}」：{faction.name} 陈词「{result.get('for', '')}」；"
                             f"{opp.name} 驳斥「{result.get('against', '')}」",
                             tick=game.clock.total_hours)
        # 议会投票：按派系支持度与成员影响力加权，成员间好感影响凝聚力
        members = [a for a in game.manager.alive()
                   if a.profession in FACTION_PROFESSIONS.get(faction.name, [])]
        power = sum(a.influence for a in members) * self._relation_factor(members)
        approve = faction.support * 0.6 + power * 2.0 + self.rng.uniform(0, 25) + swing
        if approve >= 70:
            self.active[slot] = policy
            self.history.append(policy)
            faction.support = min(100.0, faction.support + 6.0)
            game.bus.publish("policy",
                             f"{faction.name} 提案「{policy.name}」经议会通过，进入[{self.slot_name(slot)}]槽位：{policy.description}",
                             tick=game.clock.total_hours)
        else:
            faction.support = max(0.0, faction.support - 3.0)
            game.bus.publish("policy", f"{faction.name} 提案「{policy.name}」被议会否决",
                             tick=game.clock.total_hours)

    # ---------------- 派系归属与精神

    @staticmethod
    def _relation_factor(members: list) -> float:
        """成员间平均好感转化为投票凝聚力：0.5 ~ 1.5 倍。"""
        scores = [v for a in members for v in a.relations.values()]
        if not scores:
            return 1.0
        avg = sum(scores) / len(scores)
        return 1.0 + max(-0.5, min(0.5, avg / 10.0))

    def assign_factions(self, agents: list) -> None:
        for agent in agents:
            if agent.faction is None:
                for fname, profs in FACTION_PROFESSIONS.items():
                    if agent.profession in profs:
                        agent.faction = fname
                        break

    def spirit(self) -> str:
        """国家精神特质：由主导派系与生效政策合成。"""
        dominant = max(self.factions, key=lambda f: f.support)
        policies = [p.name for p in self.active.values() if p]
        core = f"{dominant.name}主导"
        if policies:
            return f"{core} · 奉行「{'」「'.join(policies[:2])}」"
        return f"{core} · 百业待兴"

    def describe(self) -> str:
        lines = ["生效政策："]
        for s in SLOTS:
            p = self.active[s]
            if p:
                eff = POLICY_EFFECTS.get(p.effect)
                eff_str = f" · {eff}" if eff else ""
                lines.append(f"  [{self.slot_name(s)}] {p.name}（{p.proposer}，第{p.day}日）{eff_str}")
            else:
                lines.append(f"  [{self.slot_name(s)}] 空缺")
        lines.append("派系支持度：")
        for f in sorted(self.factions, key=lambda f: -f.support):
            bar = "#" * int(f.support // 10)
            lines.append(f"  {f.name:<5} {bar} {f.support:.0f}")
        if self.unrest > 20:
            lines.append(f"动荡值：{self.unrest:.0f}（过高将引发叛乱）")
        return "\n".join(lines)

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {
            "factions": [f.to_dict() for f in self.factions],
            "active": {s: (p.to_dict() if p else None) for s, p in self.active.items()},
            "history": [p.to_dict() for p in self.history[-30:]],
            "unrest": self.unrest,
            "war_target_id": self.war_target_id,
        }

    def load_dict(self, data: dict) -> None:
        self.factions = [Faction.from_dict(d) for d in data.get("factions", [])]
        self.active = {s: (Policy.from_dict(d) if d else None)
                       for s, d in data.get("active", {}).items()}
        self.history = [Policy.from_dict(d) for d in data.get("history", [])]
        self.unrest = float(data.get("unrest", 0))
        self.war_target_id = data.get("war_target_id")
