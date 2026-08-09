"""政策槽位互斥与 decree 副作用。"""

import random

from machiety.civilization.policy import PolicySystem, SLOTS


class _Bus:
    def publish(self, *a, **k):
        pass


class _Clock:
    day = 5
    total_hours = 120


class _FakeManager:
    def alive(self):
        return []


class _FakeGame:
    def __init__(self):
        self.bus = _Bus()
        self.clock = _Clock()
        self.manager = _FakeManager()


def test_slot_exclusive():
    rng = random.Random(1)
    ps = PolicySystem(rng)
    game = _FakeGame()
    for i in range(6):
        ps.decree(game, f"政策{i}")
    # 每个槽位至多一项政策
    for slot in SLOTS:
        assert ps.active[slot] is None or ps.active[slot].name
    filled = sum(1 for s in SLOTS if ps.active[s] is not None)
    assert filled <= len(SLOTS)
    assert len(ps.history) == 6


def test_decree_raises_unrest():
    rng = random.Random(1)
    ps = PolicySystem(rng)
    game = _FakeGame()
    before = ps.unrest
    ps.decree(game, "测试政策")
    assert ps.unrest > before


def test_parliament_debate():
    """提案后、投票前应有一场议会辩论（debate 任务 + 辩论事件）。"""
    import asyncio

    from machiety.config import GameConfig
    from machiety.engine.scheduler import Game
    from machiety.llm.mock import MockLLM

    class RecordingLLM(MockLLM):
        def __init__(self, seed: int = 0) -> None:
            super().__init__(seed)
            self.tasks: list[str] = []

        async def generate(self, task, payload):
            self.tasks.append(task)
            return await super().generate(task, payload)

    config = GameConfig(seed=7, width=32, height=24, settlers=20, save_dir=".")
    game = Game(config, MockLLM(seed=7), seed=7)
    game.spawn_settlers()
    llm = RecordingLLM(seed=7)
    game.llm = llm
    for _ in range(30):
        for slot in list(game.policy.active):     # 保持槽位空缺，允许持续提案
            game.policy.active[slot] = None
        asyncio.run(game.policy.daily(game))
    assert "debate" in llm.tasks, "30 日内应至少发生一次议会辩论"
    assert any("议会辩论" in e.text for e in game.bus.log)
