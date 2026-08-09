"""顶部状态栏：纪元 | 时代 | 人口 | 国家精神 | 生效政策。"""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """纪元 | 时代 | 人口 | 国家精神 | 生效政策。"""

    def update_status(self, game) -> None:
        policies = [p.name for p in game.policy.active.values() if p]
        policy_str = "、".join(policies[:2]) if policies else "无政策"
        self.update(
            f"[bold #c9a227]{game.clock.date_str}[/bold #c9a227] | "
            f"[#4a9aaa]{game.epoch.era}时代[/#4a9aaa] | "
            f"人口{len(game.manager.alive())} | {game.policy.spirit()} | "
            f"政策:{policy_str}"
        )
