"""祈愿板：祈愿生成、列表、回应恩宠、超期消散。"""

import asyncio

from machiety.commands.effects import execute_command
from machiety.commands.parser import parse_command
from machiety.config import GameConfig
from machiety.engine.reaction import Prayer
from machiety.engine.scheduler import Game
from machiety.llm.mock import MockLLM


def _game() -> Game:
    config = GameConfig(seed=42, width=32, height=24, settlers=12, save_dir=".")
    return Game(config, MockLLM(seed=42), seed=42)


def test_daily_eventually_generates_prayer():
    game = _game()
    game.spawn_settlers()
    for _ in range(40):
        asyncio.run(game.prayers.daily(game))
        if game.prayers.prayers:
            break
    assert game.prayers.prayers, "40 日内应至少产生一条祈愿"


def test_grant_favors_agent():
    game = _game()
    game.spawn_settlers()
    agent = game.manager.alive()[0]
    game.prayers.prayers.append(
        Prayer(agent.name, "愿天上赐下食物", "gift", agent.name, day=game.clock.day))
    result = asyncio.run(execute_command(game, parse_command(f"gift {agent.name} food")))
    assert "祈祷得到了回应" in result.text
    assert not game.prayers.prayers
    all_mem = agent.memory.observations + agent.memory.summaries + agent.memory.core
    assert any("祈祷" in m.text for m in all_mem)


def test_prayers_command_lists():
    game = _game()
    game.spawn_settlers()
    agent = game.manager.alive()[0]
    game.prayers.prayers.append(
        Prayer(agent.name, "愿神谕垂怜", "miracle", "", day=game.clock.day))
    result = asyncio.run(execute_command(game, parse_command("prayers")))
    assert agent.name in result.text and "愿神谕垂怜" in result.text


def test_expired_prayer_fades():
    game = _game()
    game.spawn_settlers()
    game.prayers.prayers.append(
        Prayer("无名者", "旧日的祈愿", "gift", "", day=game.clock.day - 7))
    asyncio.run(game.prayers.daily(game))
    assert not game.prayers.prayers
