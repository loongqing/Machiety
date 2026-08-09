"""批次一~三新功能回归：干旱结算、编年史往返、城邦宣战合并、节流模拟、废墟持久化。"""

import asyncio
import tempfile
from pathlib import Path

from machiety.agents.agent import Agent
from machiety.config import GameConfig
from machiety.engine.scheduler import Game
from machiety.llm.mock import MockLLM
from machiety.persistence.saver import load_game, save_game


def _make_game(tmp: Path, seed: int = 42) -> Game:
    config = GameConfig(seed=seed, width=32, height=24, settlers=12, save_dir=str(tmp))
    return Game(config, MockLLM(seed=seed), seed=seed)


# ---------------- 干旱灾难解析与结算

def test_drought_parse():
    from machiety.commands.parser import parse_command
    cmd = parse_command("disaster drought 10,10")
    assert cmd.name == "disaster" and cmd.args == ["drought", "10,10"]


def test_drought_effects_settle():
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        x, y = game.spawn_x, game.spawn_y
        # 布置：半径内谷物地块、定居点存粮、角色
        tile = game.world.tile(x + 1, y)
        tile.resource, tile.resource_amount = "grain", 20
        s = game.cities.found(game, x, y, "旱城")
        s.food_stock = 100.0
        agent = game.manager.alive()[0]
        agent.x, agent.y = x, y
        survival_before = agent.needs["survival"]
        food_pool_before = game.tech.pool.get("food", 0.0)

        game.unleash_disaster("drought", x, y)
        while game.clock.hour != 12:      # 推进到正午结算
            game.clock.tick()
        game._disasters_tick()

        assert tile.resource_amount < 20
        assert s.food_stock < 100.0
        assert agent.needs["survival"] < survival_before
        assert game.tech.pool.get("food", 0.0) > food_pool_before   # 催生灌溉灵感


# ---------------- 编年史与新字段存档往返

def test_chronicle_and_new_fields_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        assert len(game.bus.chronicle) >= 1        # founding + 城邦发现
        prophet = game.manager.alive()[0]
        prophet.prophet = True
        tile = game.world.tile(game.spawn_x, game.spawn_y)
        tile.ruins = True

        save_game(game, "feat")
        loaded = load_game("feat", game.config, MockLLM(seed=42))

        assert len(loaded.bus.chronicle) == len(game.bus.chronicle)
        assert loaded.bus.chronicle[0].text == game.bus.chronicle[0].text
        restored = next(a for a in loaded.manager.agents if a.id == prophet.id)
        assert restored.prophet is True
        assert loaded.world.tile(game.spawn_x, game.spawn_y).ruins is True
        # 外邦城邦标记往返
        foreign = [s for s in game.cities.settlements if s.foreign]
        if foreign:
            lf = loaded.cities.by_name(foreign[0].name)
            assert lf is not None and lf.foreign is True


def test_ruins_persist_isolated():
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        t = game.world.tile(5, 5)
        t.ruins = True
        save_game(game, "ruins")
        loaded = load_game("ruins", game.config, MockLLM(seed=42))
        assert loaded.world.tile(5, 5).ruins is True
        assert loaded.world.tile(6, 6).ruins is False


# ---------------- 城邦生成与宣战合并

class WinningLLM(MockLLM):
    """战争裁决恒胜的测试替身。"""

    async def generate(self, task, payload):
        if task == "adjudicate":
            return {"winner": payload["a"]["name"], "loser": payload["b"]["name"],
                    "outcome": "测试胜利", "spoils": "无"}
        return await super().generate(task, payload)


def test_city_states_spawn():
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        foreign = [s for s in game.cities.settlements if s.foreign]
        assert len(foreign) >= 1
        npcs = [a for a in game.manager.agents if a.is_foreign]
        assert len(npcs) >= 5
        for npc in npcs:
            assert npc.settlement_id in {s.id for s in foreign}


def test_war_march_and_annex():
    with tempfile.TemporaryDirectory() as tmp:
        config = GameConfig(seed=42, width=32, height=24, settlers=12, save_dir=tmp)
        game = Game(config, WinningLLM(seed=42), seed=42)
        game.spawn_settlers()
        target = next(s for s in game.cities.settlements if s.foreign)

        # 编组国军：放到目标旁的可通行格
        spot = next(t for t in game.world.tiles_in_radius(target.x, target.y, 3)
                    if t.passable)
        soldiers = []
        for _ in range(6):
            a = Agent.spawn(game.manager.new_id(), game.rng, spot.x, spot.y)
            a.profession = "soldier"
            game.manager.add(a)
            soldiers.append(a)

        game.policy.decree(game, "向外邦宣战")
        assert game.policy.war_target_id == target.id

        for _ in range(24):                          # 行军直至抵达并裁决
            asyncio.run(game.policy.war_tick(game))
            if not target.foreign:
                break
        assert target.foreign is False               # 城邦并入
        assert game.policy.war_target_id is None
        assert all(not a.is_foreign for a in game.manager.agents
                   if a.settlement_id == target.id)
        assert any("并入" in e.text for e in game.bus.chronicle)


def test_war_march_moves_soldier():
    with tempfile.TemporaryDirectory() as tmp:
        config = GameConfig(seed=42, width=32, height=24, settlers=12, save_dir=tmp)
        game = Game(config, MockLLM(seed=42), seed=42)
        game.spawn_settlers()
        target = next(s for s in game.cities.settlements if s.foreign)
        a = Agent.spawn(game.manager.new_id(), game.rng, game.spawn_x, game.spawn_y)
        a.profession = "soldier"
        game.manager.add(a)
        game.policy.war_target_id = target.id
        d0 = abs(a.x - target.x) + abs(a.y - target.y)
        asyncio.run(game.policy.war_tick(game))
        d1 = abs(a.x - target.x) + abs(a.y - target.y)
        assert game.policy.war_target_id in (None, target.id)
        if game.policy.war_target_id == target.id:
            assert d1 < d0


# ---------------- 节流模式仍产出事件

def test_economy_mode_still_produces_events():
    with tempfile.TemporaryDirectory() as tmp:
        config = GameConfig(seed=42, width=32, height=24, settlers=12, save_dir=tmp)
        config.llm.economy = True
        game = Game(config, MockLLM(seed=42), seed=42)
        game.spawn_settlers()
        # 4 天窗口：节流模式仍会产出冲突/顿悟/政策等事件（不依赖某一天的随机掷骰）
        asyncio.run(game.skip_days(4))
        assert len(game.bus.log) >= 3
        assert len(game.manager.alive()) > 0
        assert game.llm.calls > 0


# ---------------- 存档版本化

def test_schema_version_written():
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        path = save_game(game, "ver")
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        conn.close()
        assert row is not None and int(row[0]) == 4


def test_future_version_rejected():
    import sqlite3
    from machiety.persistence.saver import SaveVersionError
    with tempfile.TemporaryDirectory() as tmp:
        game = _make_game(Path(tmp))
        game.spawn_settlers()
        path = save_game(game, "future")
        conn = sqlite3.connect(path)
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        try:
            load_game("future", game.config, MockLLM(seed=42))
            assert False, "应抛出 SaveVersionError"
        except SaveVersionError:
            pass


# ---------------- 灾难应对会议

def test_disaster_council_buff():
    """灾难落在定居点附近 → 次日开会 → buff 生效 3 日后到期。"""
    with tempfile.TemporaryDirectory() as tmp:
        config = GameConfig(seed=42, width=32, height=24, settlers=20, save_dir=str(tmp))
        game = Game(config, MockLLM(seed=42), seed=42)
        game.spawn_settlers()
        s = game.cities.found(game, game.spawn_x, game.spawn_y)
        game.unleash_disaster("flood", s.x, s.y)
        assert game.pending_councils, "定居点受灾应登记应对会议"
        asyncio.run(game._councils_daily())
        assert not game.pending_councils
        assert game.council_buffs and game.council_buffs[0]["settlement_id"] == s.id
        assert any(e.kind == "council" for e in game.bus.log)
        for _ in range(3):
            asyncio.run(game._councils_daily())
        assert not game.council_buffs, "buff 应在 3 日后到期"
