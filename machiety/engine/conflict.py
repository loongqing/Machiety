"""冲突裁决：资源争夺等冲突由 LLM 根据人格、地位、历史记忆裁决。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.agent import Agent
    from ..engine.scheduler import Game


async def resolve_conflict(game: "Game", a: "Agent", b: "Agent", reason: str) -> None:
    payload = {
        "a": {"name": a.name, "profession": a.profession,
              "influence": round(a.influence * a.personality.conflict_power(), 2),
              "mood": a.mood},
        "b": {"name": b.name, "profession": b.profession,
              "influence": round(b.influence * b.personality.conflict_power(), 2),
              "mood": b.mood},
        "reason": reason,
        "tier": "large",
    }
    result = await game.llm.generate("adjudicate", payload)
    winner = a if result.get("winner") == a.name else b
    loser = b if winner is a else a
    outcome = result.get("outcome", f"{winner.name} 压过了 {loser.name}")

    # 战利品：粮食或财富转移
    spoils = result.get("spoils", "food")
    if spoils == "food" and loser.food > 0:
        taken = min(2, loser.food)
        loser.inventory["food"] -= taken
        winner.inventory["food"] = winner.inventory.get("food", 0) + taken
    elif spoils == "wealth" and loser.wealth > 0:
        taken = min(2, loser.wealth)
        loser.wealth -= taken
        winner.wealth += taken

    winner.influence += 0.8
    loser.influence = max(0.5, loser.influence - 0.4)
    loser.needs["safety"] = max(0.0, loser.needs["safety"] - 0.15)
    winner.needs["esteem"] = min(1.0, winner.needs["esteem"] + 0.1)

    tick = game.clock.total_hours
    winner.remember(f"冲突：{outcome}", tick, importance=6.0)
    loser.remember(f"冲突：{outcome}，我心怀不满", tick, importance=6.0)
    game.tech.add_inspiration("war", 1.0)
    game.bus.publish("combat", f"{a.name} 与 {b.name} 因{reason}爆发冲突 —— {outcome}",
                     tick=tick, x=a.x, y=a.y)
