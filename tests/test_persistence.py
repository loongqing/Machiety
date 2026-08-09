"""存档往返一致 + 模拟冒烟。"""

import asyncio
import tempfile
from pathlib import Path

from machiety.config import GameConfig
from machiety.engine.scheduler import Game
from machiety.llm.mock import MockLLM
from machiety.persistence.saver import load_game, save_game


def _make_game(tmp: Path) -> Game:
    config = GameConfig(seed=42, width=32, height=24, settlers=12, save_dir=str(tmp))
    return Game(config, MockLLM(seed=42), seed=42)


def test_simulate_and_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        # 冒烟：跑半天不抛异常
        asyncio.run(game.skip_days(1))
        assert len(game.manager.alive()) > 0
        assert game.clock.day >= 1

        save_game(game, "roundtrip")
        loaded = load_game("roundtrip", game.config, MockLLM(seed=42))
        assert loaded.seed == game.seed
        assert loaded.clock.total_hours == game.clock.total_hours
        assert len(loaded.manager.agents) == len(game.manager.agents)
        original = game.manager.agents[0]
        restored = next(a for a in loaded.manager.agents if a.id == original.id)
        assert restored.name == original.name
        assert len(restored.memory.core) == len(original.memory.core)
        # 新档 roundtrip：world_gen 版本保留，地貌一致
        assert [t.terrain for t in loaded.world.tiles] == \
            [t.terrain for t in game.world.tiles]
        assert loaded.world.tile(0, 0).elevation == game.world.tile(0, 0).elevation


def test_old_save_defaults_to_v1_world():
    """无 world_gen 字段的旧档 → 用 v1 算法重建地貌（旧档地貌不变）。"""
    from machiety.engine.clock import Clock
    from machiety.engine.world import World

    config = GameConfig(seed=42, width=32, height=24, settlers=5, save_dir=".")
    data = {
        "meta": {"seed": 42, "width": 32, "height": 24, "version": 1},
        "clock": Clock().to_dict(),
        "world_dynamic": [],
        "agents": [],
        "tech": {}, "policy": {}, "cities": {}, "great": {}, "wonders": {}, "epoch": {},
        "disasters": [], "watched": None, "chronicle": [],
    }
    game = Game.from_save_dict(config, MockLLM(seed=42), data)
    v1 = World.generate(32, 24, 42, version=1)
    assert [t.terrain for t in game.world.tiles] == [t.terrain for t in v1.tiles]


def test_agentic_state_roundtrip():
    """反应波、祈愿、会议状态纳入存档往返。"""
    from machiety.engine.reaction import Prayer

    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        asyncio.run(game.reaction.on_intervention(
            game, "miracle", "测试神谕", game.spawn_x, game.spawn_y))
        agent = game.manager.alive()[0]
        game.prayers.prayers.append(
            Prayer(agent.name, "愿神垂怜", "miracle", "", day=game.clock.day))
        game.pending_councils.append({"settlement_id": 1, "dtype": "flood", "day": 0})
        game.council_buffs.append({"settlement_id": 1, "focus": "food", "days_left": 2})

        save_game(game, "agentic")
        loaded = load_game("agentic", game.config, MockLLM(seed=42))
        assert len(loaded.reaction.waves) == 1
        assert loaded.reaction.waves[0].text == "测试神谕"
        assert loaded.reaction.waves[0].reactions
        assert len(loaded.prayers.prayers) == 1
        assert loaded.prayers.prayers[0].agent_name == agent.name
        assert loaded.pending_councils[0]["dtype"] == "flood"
        assert loaded.council_buffs[0]["focus"] == "food"
