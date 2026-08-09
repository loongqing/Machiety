"""时代更迭：综合科技、制度、文化指数自动判定当前时代。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine.scheduler import Game

ERAS = ["远古", "古典", "中古", "文艺复兴", "工业", "现代"]
ERA_THRESHOLDS = [0, 25, 60, 110, 170, 240]   # 进入各时代所需分数


class EpochSystem:
    def __init__(self) -> None:
        self.era_index = 0
        self.cultural_events = 0

    @property
    def era(self) -> str:
        return ERAS[self.era_index]

    def score(self, game: "Game") -> float:
        tech_score = len(game.tech.techs) * 3.0
        tech_score += sum(t.spread for t in game.tech.techs)
        slot_filled = sum(1 for p in game.policy.active.values() if p)
        policy_score = slot_filled * 4.0
        city_score = sum(2.0 for s in game.cities.settlements if not s.foreign)
        culture_score = self.cultural_events * 1.0
        wonder_score = sum(3.0 for w in game.wonders.wonders if w.status == "completed")
        return tech_score + policy_score + city_score + culture_score + wonder_score

    def progress(self, game: "Game") -> tuple[float, float]:
        """返回 (当前分数, 下一时代门槛)。"""
        if self.era_index >= len(ERAS) - 1:
            return self.score(game), float("inf")
        return self.score(game), ERA_THRESHOLDS[self.era_index + 1]

    async def daily(self, game: "Game") -> None:
        if self.era_index >= len(ERAS) - 1:
            return
        s, threshold = self.progress(game)
        if s >= threshold:
            self.era_index += 1
            result = await game.llm.generate("era_event", {"era": self.era, "tier": "large"})
            game.bus.publish("era", result.get("text", f"文明迈入{self.era}时代"),
                             tick=game.clock.total_hours)

    def describe(self, game: "Game") -> str:
        s, threshold = self.progress(game)
        lines = [f"当前时代：{self.era}", f"时代指数：{s:.1f}"]
        if threshold != float("inf"):
            pct = min(100, int(s / threshold * 100))
            lines.append(f"下一时代[{ERAS[self.era_index + 1]}]进度：[{pct}%]（{s:.1f}/{threshold:.0f}）")
        else:
            lines.append("文明已抵达现代，未来由你书写。")
        lines.append(f"文化事件累计：{self.cultural_events}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"era_index": self.era_index, "cultural_events": self.cultural_events}

    def load_dict(self, data: dict) -> None:
        self.era_index = int(data.get("era_index", 0))
        self.cultural_events = int(data.get("cultural_events", 0))
