"""干预反应链：波生成、传播扩散、衰减消亡、降级与节流。"""

import asyncio

from machiety.config import GameConfig
from machiety.engine.scheduler import Game
from machiety.llm.base import BaseLLM
from machiety.llm.mock import MockLLM


def _game(economy: bool = False, settlers: int = 12) -> Game:
    config = GameConfig(seed=42, width=32, height=24, settlers=settlers, save_dir=".")
    config.llm.economy = economy
    return Game(config, MockLLM(seed=42), seed=42)


def test_miracle_creates_wave():
    game = _game()
    game.spawn_settlers()
    asyncio.run(game.reaction.on_intervention(
        game, "miracle", "雨水将赐福此地", game.spawn_x, game.spawn_y))
    assert game.reaction.waves
    wave = game.reaction.waves[-1]
    assert wave.kind == "miracle" and wave.text == "雨水将赐福此地"
    assert wave.reactions and wave.carriers
    assert len(wave.reactions) <= 4


def test_wave_spreads_then_dies():
    game = _game(settlers=6)
    game.spawn_settlers()
    a, b = game.manager.alive()[:2]
    b.x, b.y = a.x, a.y          # 同格制造传播条件
    asyncio.run(game.reaction.on_intervention(game, "miracle", "星辰坠落", a.x, a.y))
    wave = game.reaction.waves[-1]
    listener = b if wave.carriers[0] == a.name else a
    for _ in range(3):
        game.reaction.hourly(game)
    assert any("听到" in m.text for m in listener.memory.observations)
    for _ in range(20):
        game.reaction.hourly(game)
    assert not game.reaction.waves


def test_interpret_failure_falls_back():
    class BrokenLLM(BaseLLM):
        async def generate(self, task, payload):
            return {}
    config = GameConfig(seed=42, width=32, height=24, settlers=8, save_dir=".")
    game = Game(config, BrokenLLM(seed=1), seed=42)
    game.spawn_settlers()
    asyncio.run(game.reaction.on_intervention(
        game, "gift", "天降神赐", game.spawn_x, game.spawn_y))
    wave = game.reaction.waves[-1]
    assert wave.reactions
    assert all(r.spread_line for r in wave.reactions.values())


def test_economy_single_rep():
    game = _game(economy=True)
    game.spawn_settlers()
    asyncio.run(game.reaction.on_intervention(
        game, "miracle", "神谕", game.spawn_x, game.spawn_y))
    assert len(game.reaction.waves[-1].reactions) == 1
