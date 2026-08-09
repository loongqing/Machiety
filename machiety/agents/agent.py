"""国民智能体：人格、需求、目标、记忆与社会身份的载体。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .memory import MemoryStream
from .personality import Personality

PROFESSIONS = ["farmer", "hunter", "fisher", "artisan", "merchant",
               "soldier", "official", "priest", "scholar"]
PROFESSION_NAMES = {
    "farmer": "农民", "hunter": "猎人", "fisher": "渔夫", "artisan": "工匠",
    "merchant": "商人", "soldier": "士兵", "official": "官员",
    "priest": "祭司", "scholar": "学者",
}
PROFESSION_GLYPH = {
    "farmer": "F", "hunter": "H", "fisher": "i", "artisan": "C",
    "merchant": "$", "soldier": "!", "official": "O",
    "priest": "+", "scholar": "?",
}

NEED_KINDS = ["survival", "safety", "social", "esteem", "self_actualization"]
NEED_NAMES = {
    "survival": "生存", "safety": "安全", "social": "社交",
    "esteem": "尊重", "self_actualization": "自我实现",
}

SYLLABLES = ["卡", "洛", "米", "瑟", "塔", "鲁", "薇", "诺", "伊", "哈",
             "德", "菲", "奥", "赞", "黎", "柯", "艾", "索"]
NAME_TAILS = ["恩", "斯", "娜", "里克", "文", "拉斯", "米尔", "多", "萨", "丝", "顿", "娅"]

INITIAL_GOALS = ["安稳度日", "积累财富", "获得权力", "探索未知", "寻找信仰", "传宗接代"]


def generate_name(rng: random.Random) -> str:
    return rng.choice(SYLLABLES) + rng.choice(NAME_TAILS) + (rng.choice(SYLLABLES) if rng.random() < 0.3 else "")


@dataclass
class Agent:
    id: int
    name: str
    x: int
    y: int
    profession: str = "farmer"
    age: int = 20
    lifespan: int = 75
    alive: bool = True
    mood: str = "平静"
    personality: Personality = field(default_factory=Personality)
    needs: dict[str, float] = field(default_factory=lambda: {k: 0.6 for k in NEED_KINDS})
    goals: list[str] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=dict)
    wealth: int = 0
    influence: float = 1.0
    honor: float = 0.0
    achievement: int = 0        # 卓越成就计数（顿悟/征服/倡议奇观/荣誉），伟人涌现的门槛
    faction: str | None = None
    settlement_id: int | None = None
    relations: dict[str, int] = field(default_factory=dict)   # 对方名字 -> 好感
    memory: MemoryStream = field(default_factory=MemoryStream)
    great_title: str | None = None
    great_gift: str | None = None
    great_gift_kind: str | None = None   # 天赋落地的效果种类（见 great_people.GIFT_KINDS）
    cause_of_death: str | None = None
    prev_x: int | None = None       # 上一时刻坐标（地图拖影）
    prev_y: int | None = None
    prophet: bool = False           # 玩家化身：先知
    is_foreign: bool = False        # 外邦城邦成员
    _plan_cache: dict = field(default_factory=dict, repr=False)   # 节流模式规划缓存（运行时）

    # ---------------- 工厂

    @classmethod
    def spawn(cls, agent_id: int, rng: random.Random, x: int, y: int, tick: int = 0) -> "Agent":
        agent = cls(
            id=agent_id,
            name=generate_name(rng),
            x=x, y=y,
            profession=rng.choice(PROFESSIONS),
            age=rng.randint(16, 45),
            lifespan=rng.randint(60, 90),
            personality=Personality.generate(rng),
            goals=rng.sample(INITIAL_GOALS, k=rng.randint(1, 2)),
            inventory={"food": rng.randint(3, 8)},
            wealth=rng.randint(0, 10),
        )
        agent.needs = {
            "survival": round(rng.uniform(0.5, 0.9), 2),
            "safety": round(rng.uniform(0.5, 0.9), 2),
            "social": round(rng.uniform(0.4, 0.8), 2),
            "esteem": round(rng.uniform(0.3, 0.7), 2),
            "self_actualization": round(rng.uniform(0.2, 0.6), 2),
        }
        agent.memory.add(f"{agent.name} 随殖民船队抵达新大陆，在陌生的土地上开始了新生活。",
                         tick=tick, importance=8.0)
        return agent

    # ---------------- 行为辅助

    @property
    def food(self) -> int:
        return self.inventory.get("food", 0)

    def dominant_need(self) -> str:
        return min(self.needs, key=lambda k: self.needs[k])

    def clamp_needs(self) -> None:
        for k in self.needs:
            self.needs[k] = max(0.0, min(1.0, self.needs[k]))

    def remember(self, text: str, tick: int, importance: float = 4.0) -> None:
        self.memory.add(text, tick=tick, importance=importance)

    # ---------------- 展示

    @property
    def profession_name(self) -> str:
        return PROFESSION_NAMES.get(self.profession, self.profession)

    def describe(self) -> str:
        lines = [
            f"{self.name}（{self.profession_name}，{self.age}岁） 坐标({self.x},{self.y})",
            f"性格：{self.personality.describe()}  心境：{self.mood}",
            f"需求：{' '.join(f'{NEED_NAMES[k]}{v:.0%}' for k, v in self.needs.items())}",
            f"目标：{'；'.join(self.goals) if self.goals else '无'}",
            f"存粮：{self.food}  财富：{self.wealth}  影响力：{self.influence:.1f}  荣誉：{self.honor:.0f}",
        ]
        if self.faction:
            lines.append(f"派系：{self.faction}")
        if self.great_title:
            lines.append(f"伟人称号：{self.great_title} —— {self.great_gift}")
        return "\n".join(lines)

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "x": self.x, "y": self.y,
            "profession": self.profession, "age": self.age, "lifespan": self.lifespan,
            "alive": self.alive, "mood": self.mood,
            "personality": self.personality.to_dict(),
            "needs": self.needs, "goals": self.goals,
            "inventory": self.inventory, "wealth": self.wealth,
            "influence": self.influence, "honor": self.honor,
            "achievement": self.achievement,
            "faction": self.faction, "settlement_id": self.settlement_id,
            "relations": self.relations,
            "memory": self.memory.to_dict(),
            "great_title": self.great_title, "great_gift": self.great_gift,
            "great_gift_kind": self.great_gift_kind,
            "cause_of_death": self.cause_of_death,
            "prev_x": self.prev_x, "prev_y": self.prev_y,
            "prophet": self.prophet, "is_foreign": self.is_foreign,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        agent = cls(
            id=int(data["id"]), name=data["name"], x=int(data["x"]), y=int(data["y"]),
            profession=data.get("profession", "farmer"),
            age=int(data.get("age", 20)), lifespan=int(data.get("lifespan", 75)),
            alive=bool(data.get("alive", True)), mood=data.get("mood", "平静"),
        )
        agent.personality = Personality.from_dict(data.get("personality", {}))
        agent.needs = {k: float(v) for k, v in data.get("needs", {}).items()} or agent.needs
        agent.goals = list(data.get("goals", []))
        agent.inventory = dict(data.get("inventory", {}))
        agent.wealth = int(data.get("wealth", 0))
        agent.influence = float(data.get("influence", 1.0))
        agent.honor = float(data.get("honor", 0.0))
        agent.achievement = int(data.get("achievement", 0))
        agent.faction = data.get("faction")
        agent.settlement_id = data.get("settlement_id")
        agent.relations = {k: int(v) for k, v in data.get("relations", {}).items()}
        agent.memory = MemoryStream.from_dict(data.get("memory", {}))
        agent.great_title = data.get("great_title")
        agent.great_gift = data.get("great_gift")
        agent.great_gift_kind = data.get("great_gift_kind")
        agent.cause_of_death = data.get("cause_of_death")
        agent.prev_x = data.get("prev_x")
        agent.prev_y = data.get("prev_y")
        agent.prophet = bool(data.get("prophet", False))
        agent.is_foreign = bool(data.get("is_foreign", False))
        return agent
