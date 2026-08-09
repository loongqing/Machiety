"""指令解析：设计稿 §3 全部指令可被识别。"""

from machiety.commands.parser import parse_command


def test_all_commands_parse():
    cases = [
        ("watch 卡恩", "watch", ["卡恩"]),
        ('miracle "雨水将赐福此地"', "miracle", ["雨水将赐福此地"]),
        ("disaster drought 晨曦城", "disaster", ["drought", "晨曦城"]),
        ('inspire idea "灌溉"', "inspire", ["idea", "灌溉"]),
        ('inspire 卡恩 "你曾见过大海"', "inspire", ["卡恩", "你曾见过大海"]),
        ("gift 卡恩 iron", "gift", ["卡恩", "iron"]),
        ('decree "自由市集"', "decree", ["自由市集"]),
        ("fund 晨曦城 market", "fund", ["晨曦城", "market"]),
        ('launch wonder "大灯塔"', "launch", ["wonder", "大灯塔"]),
        ("honor 卡恩", "honor", ["卡恩"]),
        ("skip 3", "skip", ["3"]),
        ("map", "map", []),
        ("epoch", "epoch", []),
        ("policy", "policy", []),
        ("spirit", "spirit", []),
        ("save test", "save", ["test"]),
        ("load test", "load", ["test"]),
        ("prayers", "prayers", []),
        ('talk 卡恩 "你所求为何"', "talk", ["卡恩", "你所求为何"]),
    ]
    for raw, name, args in cases:
        cmd = parse_command(raw)
        assert cmd is not None, raw
        assert cmd.name == name, raw
        assert cmd.args == args, raw


def test_empty_and_case():
    assert parse_command("") is None
    assert parse_command("   ") is None
    assert parse_command("WATCH 卡恩").name == "watch"


def _talk_game():
    from machiety.config import GameConfig
    from machiety.engine.scheduler import Game
    from machiety.llm.mock import MockLLM

    config = GameConfig(seed=42, width=32, height=24, settlers=8, save_dir=".")
    game = Game(config, MockLLM(seed=42), seed=42)
    game.spawn_settlers()
    return game


def test_talk_command_replies():
    """talk 指令：角色回应并记住神的对话。"""
    import asyncio

    from machiety.commands.effects import execute_command

    game = _talk_game()
    agent = game.manager.alive()[0]
    result = asyncio.run(execute_command(
        game, parse_command(f'talk {agent.name} "你所求为何"')))
    assert agent.name in result.text
    all_mem = agent.memory.observations + agent.memory.summaries + agent.memory.core
    assert any("神明亲自对我说话" in m.text for m in all_mem)


def test_talk_unknown_agent():
    import asyncio

    from machiety.commands.effects import execute_command

    game = _talk_game()
    result = asyncio.run(execute_command(game, parse_command('talk 不存在的人 "你好"')))
    assert "找不到" in result.text
