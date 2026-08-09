"""世界生成：地形合法性、确定性、出生点可达。"""

from machiety.engine.world import (FOREST, HILL, MOUNTAIN, OCEAN, PLAIN,
                                   RIVER, World)


def test_generate_bounds():
    w = World.generate(48, 32, seed=42)
    assert len(w.tiles) == 48 * 32
    land = [t for t in w.tiles if t.terrain not in (OCEAN, MOUNTAIN)]
    assert 0 < len(land) < len(w.tiles)


def test_deterministic():
    a = World.generate(40, 28, seed=7)
    b = World.generate(40, 28, seed=7)
    assert [t.terrain for t in a.tiles] == [t.terrain for t in b.tiles]
    c = World.generate(40, 28, seed=8)
    assert [t.terrain for t in a.tiles] != [t.terrain for t in c.tiles]


def test_spawn_passable():
    import random
    w = World.generate(48, 32, seed=42)
    rng = random.Random(1)
    x, y = w.find_spawn(rng)
    t = w.tile(x, y)
    assert t is not None and t.passable


def test_resources_placed():
    w = World.generate(48, 32, seed=42)
    assert any(t.resource for t in w.tiles)


def test_world_v2_diverse():
    """v2（默认）：六种地形齐全，陆地占比合理。"""
    w = World.generate(64, 40, seed=42)
    kinds = {t.terrain for t in w.tiles}
    assert kinds == {OCEAN, PLAIN, HILL, FOREST, MOUNTAIN, RIVER}, kinds
    land = [t for t in w.tiles if t.terrain not in (OCEAN, MOUNTAIN)]
    ratio = len(land) / len(w.tiles)
    assert 0.15 < ratio < 0.75, f"陆地占比异常: {ratio:.0%}"


def test_world_v2_deterministic():
    a = World.generate(40, 28, seed=7)
    b = World.generate(40, 28, seed=7)
    assert [t.terrain for t in a.tiles] == [t.terrain for t in b.tiles]


def test_world_gen_versions_differ():
    """v1 与 v2 算法产生不同地貌（旧存档地貌不受新算法影响）。"""
    a = World.generate(48, 32, seed=42, version=1)
    b = World.generate(48, 32, seed=42, version=2)
    assert [t.terrain for t in a.tiles] != [t.terrain for t in b.tiles]
