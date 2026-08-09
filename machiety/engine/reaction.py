"""干预反应链与祈愿板：玩家的神迹被解读、传播与回应。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..agents.agent import NEED_NAMES

if TYPE_CHECKING:
    from .scheduler import Game

PRAYER_INTENTS = {"miracle", "gift", "disaster", "decree", "fund", "inspire"}
COUNCIL_FOCUS = {"food", "build", "spirit", "safety"}

# 祈愿展示：每种 intent 暗示的回应方式
INTENT_HINTS = {
    "miracle": "miracle 神谕", "gift": "gift 赏赐", "disaster": "disaster 降灾",
    "decree": "decree 法令", "fund": "fund 赐福", "inspire": "inspire 启示",
}

_WORD = {1: "吉兆", 0: "考验", -1: "警示"}


@dataclass
class Reaction:
    name: str
    interpretation: str
    spread_line: str
    sentiment: int = 0

    def to_dict(self) -> dict:
        return {"name": self.name, "interpretation": self.interpretation,
                "spread_line": self.spread_line, "sentiment": self.sentiment}

    @classmethod
    def from_dict(cls, d: dict) -> "Reaction":
        return cls(name=d["name"], interpretation=d["interpretation"],
                   spread_line=d["spread_line"], sentiment=int(d.get("sentiment", 0)))


@dataclass
class ReactionWave:
    kind: str
    text: str
    strength: float = 1.0
    x: int = 0
    y: int = 0
    reactions: dict[str, Reaction] = field(default_factory=dict)
    carriers: list[str] = field(default_factory=list)
    heard: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "strength": self.strength,
                "x": self.x, "y": self.y,
                "reactions": {k: r.to_dict() for k, r in self.reactions.items()},
                "carriers": self.carriers, "heard": self.heard}

    @classmethod
    def from_dict(cls, d: dict) -> "ReactionWave":
        w = cls(kind=d["kind"], text=d["text"], strength=float(d.get("strength", 1.0)),
                x=int(d.get("x", 0)), y=int(d.get("y", 0)))
        w.reactions = {k: Reaction.from_dict(v) for k, v in d.get("reactions", {}).items()}
        w.carriers = list(d.get("carriers", []))
        w.heard = list(d.get("heard", []))
        return w


class ReactionEngine:
    """干预反应链：代表解读 → 同格传播 → 衰减消亡。"""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.waves: list[ReactionWave] = []

    # ---------------- 触发

    async def on_intervention(self, game: "Game", kind: str, text: str,
                              x: int, y: int) -> None:
        economy = game.config.llm.economy
        reps = self._pick_reps(game, x, y, limit=1 if economy else 4)
        if not reps:
            return
        result = await game.llm.generate("interpret", {
            "event": {"kind": kind, "text": text},
            "reps": [{"name": a.name, "profession": a.profession_name,
                      "personality": a.personality.describe()} for a in reps],
            "tier": "small" if economy else "large",
        })
        wave = ReactionWave(kind=kind, text=text, x=x, y=y)
        by_name = {a.name: a for a in reps}
        for item in result.get("reactions", []):
            name = item.get("name", "")
            if name not in by_name or not item.get("spread_line"):
                continue
            try:
                senti = int(item.get("sentiment", 0))
            except (TypeError, ValueError):
                senti = 0
            wave.reactions[name] = Reaction(
                name=name,
                interpretation=item.get("interpretation") or item["spread_line"],
                spread_line=item["spread_line"],
                sentiment=max(-1, min(1, senti)))
        for a in reps:                       # LLM 缺失或损坏时按模板兜底
            if a.name in wave.reactions:
                continue
            senti = self.rng.choice([-1, 0, 1])
            wave.reactions[a.name] = Reaction(
                name=a.name,
                interpretation=f"{a.name} 将此事解读为神明的{_WORD[senti]}",
                spread_line=f"「{text}」降临了，{a.profession_name} {a.name} 说这是神明的{_WORD[senti]}",
                sentiment=senti)
        wave.carriers = list(wave.reactions)
        tick = game.clock.total_hours
        for name, r in wave.reactions.items():
            by_name[name].remember(f"我对「{text}」有自己的解读：{r.interpretation}",
                                   tick, importance=6.5)
            game.bus.publish("reaction", f"{name} 率先发声：{r.interpretation}",
                             tick=tick, x=x, y=y)
        self.waves.append(wave)

    def _pick_reps(self, game: "Game", x: int, y: int, limit: int) -> list:
        """代表 = 先知 + 事件在场者 + 影响力最高者。"""
        alive = [a for a in game.manager.alive() if not a.is_foreign]
        reps = [a for a in alive if a.prophet]
        reps += [a for a in game.manager.agents_at(x, y)
                 if not a.is_foreign and a not in reps]
        rest = sorted((a for a in alive if a not in reps), key=lambda a: -a.influence)
        reps += rest[:max(0, limit - len(reps))]
        return reps[:limit]

    # ---------------- 每小时传播

    def hourly(self, game: "Game") -> None:
        if not self.waves:
            return
        self._prophet_spread(game)
        tick = game.clock.total_hours
        dead = []
        for wave in self.waves:
            wave.strength -= 0.1
            if wave.strength <= 0.0:
                dead.append(wave)
                continue
            for carrier in [a for a in game.manager.alive()
                            if a.name in wave.carriers]:
                rep = wave.reactions.get(carrier.name)
                if rep is None:
                    continue
                for listener in game.manager.agents_at(carrier.x, carrier.y):
                    if listener.id == carrier.id or listener.is_foreign:
                        continue
                    if listener.name in wave.heard:
                        continue
                    wave.heard.append(listener.name)
                    listener.remember(f"我听到 {carrier.name} 说：{rep.spread_line}",
                                      tick, importance=2.0 + 4.0 * wave.strength)
                    if rep.sentiment:
                        listener.needs["safety"] += 0.03 * rep.sentiment
                        listener.needs["social"] += 0.03 * rep.sentiment
                        listener.clamp_needs()
                    if wave.strength >= 0.5 and not game.config.llm.economy \
                            and listener.name not in wave.carriers:
                        wave.carriers.append(listener.name)
        for wave in dead:
            self.waves.remove(wave)
            game.bus.publish("reaction", f"关于「{wave.text[:12]}」的议论渐渐平息",
                             tick=tick)

    def _prophet_spread(self, game: "Game") -> None:
        """背负「传播神谕」的先知向人群移动，遇人即宣讲。"""
        tick = game.clock.total_hours
        wave = next((w for w in reversed(self.waves) if w.kind == "miracle"), None)
        for prophet in [a for a in game.manager.alive()
                        if a.prophet and "传播神谕" in a.goals]:
            group = [o for o in game.manager.agents_at(prophet.x, prophet.y)
                     if o.id != prophet.id and not o.is_foreign]
            if group and wave is not None:
                rep = wave.reactions.get(prophet.name) \
                    or next(iter(wave.reactions.values()), None)
                if rep is not None:
                    for o in group:
                        if o.name not in wave.heard:
                            wave.heard.append(o.name)
                            o.remember(f"先知 {prophet.name} 向我宣讲神谕：{rep.spread_line}",
                                       tick, importance=7.0)
                    game.bus.publish("reaction", f"先知 {prophet.name} 向民众宣讲了神谕",
                                     tick=tick, x=prophet.x, y=prophet.y)
                prophet.goals.remove("传播神谕")
                continue
            # 向最近的人群迈进一步
            target, best = None, 10 ** 9
            for a in game.manager.alive():
                if a.id == prophet.id or a.is_foreign:
                    continue
                d = abs(a.x - prophet.x) + abs(a.y - prophet.y)
                if 0 < d <= 8 and d < best:
                    best, target = d, a
            if target is not None:
                self._step_toward(game, prophet, target.x, target.y)

    @staticmethod
    def _step_toward(game: "Game", agent, tx: int, ty: int) -> None:
        dx = (1 if tx > agent.x else -1) if tx != agent.x else 0
        dy = (1 if ty > agent.y else -1) if ty != agent.y else 0
        for sx, sy in ((dx, 0), (0, dy)):
            if sx == 0 and sy == 0:
                continue
            t = game.world.tile(agent.x + sx, agent.y + sy)
            if t and t.passable and not game.manager.agents_at(t.x, t.y):
                agent.prev_x, agent.prev_y = agent.x, agent.y
                agent.x, agent.y = t.x, t.y
                return

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {"waves": [w.to_dict() for w in self.waves]}

    def load_dict(self, data: dict) -> None:
        self.waves = [ReactionWave.from_dict(d) for d in data.get("waves", [])]


@dataclass
class Prayer:
    agent_name: str
    text: str
    intent: str
    target: str
    day: int

    def to_dict(self) -> dict:
        return {"agent_name": self.agent_name, "text": self.text, "intent": self.intent,
                "target": self.target, "day": self.day}

    @classmethod
    def from_dict(cls, d: dict) -> "Prayer":
        return cls(agent_name=d["agent_name"], text=d["text"], intent=d["intent"],
                   target=d.get("target", ""), day=int(d["day"]))


class PrayerBoard:
    """国民祈愿板：每日或有祈愿升起，玩家以指令回应即赐恩宠。"""

    MAX_PRAYERS = 5
    EXPIRE_DAYS = 7

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.prayers: list[Prayer] = []

    async def daily(self, game: "Game") -> None:
        tick = game.clock.total_hours
        kept = []
        for p in self.prayers:
            if game.clock.day - p.day >= self.EXPIRE_DAYS:
                game.bus.publish("prayer", f"{p.agent_name} 的祈愿未获回应，沉入了时光之河",
                                 tick=tick)
            else:
                kept.append(p)
        self.prayers = kept
        prob = 0.15 if game.config.llm.economy else 0.4
        if len(self.prayers) >= self.MAX_PRAYERS or self.rng.random() > prob:
            return
        alive = [a for a in game.manager.alive() if not a.is_foreign]
        if not alive:
            return
        # 候选：先知优先，其余按主导需求从低到高（最困苦者先祈愿）
        alive.sort(key=lambda a: (not a.prophet, a.needs[a.dominant_need()]))
        cands = alive[:3]
        result = await game.llm.generate("prayer", {
            "candidates": [{"name": a.name, "profession": a.profession_name,
                            "need": NEED_NAMES.get(a.dominant_need(), ""),
                            "settlement": self._settlement_name(game, a),
                            "mood": a.mood} for a in cands],
            "tier": "small",
        })
        by_name = {a.name: a for a in cands}
        for item in result.get("prayers", []):
            name = item.get("name", "")
            text = str(item.get("text") or "").strip()
            if name not in by_name or not text:
                continue
            if len(self.prayers) >= self.MAX_PRAYERS:
                break
            intent = item.get("intent")
            self.prayers.append(Prayer(
                agent_name=name, text=text,
                intent=intent if intent in PRAYER_INTENTS else "miracle",
                target=str(item.get("target") or ""), day=game.clock.day))
            game.bus.publish("prayer", f"{name} 向天祈祷：「{text}」", tick=tick)

    @staticmethod
    def _settlement_name(game: "Game", agent) -> str:
        s = next((x for x in game.cities.settlements
                  if x.id == agent.settlement_id), None)
        return s.name if s else ""

    def try_grant(self, game: "Game", cmd_name: str, args_text: str) -> str:
        """玩家指令若与某条祈愿匹配，则降下恩宠；返回附加提示文本。"""
        for p in list(self.prayers):
            if p.intent != cmd_name:
                continue
            if p.target and p.target not in args_text and args_text not in p.target:
                continue
            self.prayers.remove(p)
            agent = game.manager.by_name(p.agent_name)
            if agent is None:
                return ""
            agent.needs["self_actualization"] = min(
                1.0, agent.needs["self_actualization"] + 0.2)
            agent.influence += 1.0
            agent.clamp_needs()
            agent.remember("神明回应了我的祈祷，我的虔诚被听见了",
                           game.clock.total_hours, importance=9.0)
            game.bus.publish("granted", f"{agent.name} 的祈祷得到了回应，恩宠加身",
                             tick=game.clock.total_hours, x=agent.x, y=agent.y)
            return f"。{agent.name} 的祈祷得到了回应（恩宠降临）"
        return ""

    def describe(self) -> str:
        if not self.prayers:
            return "祈愿板上空空如也，民众此刻安居，别无所求"
        lines = ["悬而未决的祈愿："]
        for p in self.prayers:
            hint = INTENT_HINTS.get(p.intent, p.intent)
            tgt = f"（关乎{p.target}）" if p.target else ""
            lines.append(f"  {p.agent_name}：「{p.text}」—— 可用 {hint} 回应{tgt}（第{p.day}日）")
        return "\n".join(lines)

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {"prayers": [p.to_dict() for p in self.prayers]}

    def load_dict(self, data: dict) -> None:
        self.prayers = [Prayer.from_dict(d) for d in data.get("prayers", [])]
