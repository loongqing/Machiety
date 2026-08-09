"""地图像素风渲染与叠加符号测试。"""

import asyncio
import tempfile
import unicodedata

from rich.console import Console

from machiety.agents.agent import PROFESSION_GLYPH
from machiety.config import GameConfig
from machiety.engine.scheduler import Game
from machiety.engine.world import PLAIN
from machiety.llm.mock import MockLLM
from machiety.ui.app import MachietyApp
from machiety.ui.map_view import BORDER_COLORS, PROF_ICON

_CONSOLE = Console()


def _char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def _col_to_char_offset(plain: str, start_col: int) -> int:
    """把列偏移换算为字符偏移（跳过 CJK 宽字符）。"""
    used = 0
    for i, ch in enumerate(plain):
        if used + _char_width(ch) > start_col:
            return i
        used += _char_width(ch)
    return len(plain)


def _slice_cols(plain: str, start_col: int, width: int) -> str:
    """按终端列宽从 plain 切出从 start_col 列起的 width 列。"""
    start = _col_to_char_offset(plain, start_col)
    out, used = "", 0
    for ch in plain[start:]:
        w = _char_width(ch)
        if used + w > width:
            break
        out += ch
        used += w
    return out


def _make_game(save_dir: str, settlers: int = 10) -> Game:
    config = GameConfig(seed=7, width=32, height=24, settlers=settlers, save_dir=save_dir)
    game = Game(config, MockLLM(seed=7), seed=7)
    game.spawn_settlers()
    return game


def _probe(view, x: int, y: int):
    """渲染地图并定位 (x, y) 格：返回 (格字符, 所在行 Text, 格起始字符偏移)。"""
    view.cursor_x, view.cursor_y = x, y
    out = view.render()
    x0, y0, _, _ = view._viewport()
    line = out.split("\n")[y - y0]
    start_col = (x - x0) * view.cell_width
    return _slice_cols(line.plain, start_col, view.cell_width), line, \
        _col_to_char_offset(line.plain, start_col)


def _style_at(line, offset):
    return line.get_style_at_offset(_CONSOLE, offset)


def test_pixel_terrain_uses_half_blocks():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                # 找一个无叠加的已探索纯地形格
                tile = next(t for t in game.world.tiles
                            if t.explored and t.terrain == PLAIN
                            and t.resource_amount == 0 and t.settlement_id is None
                            and not any(a.x == t.x and a.y == t.y
                                        for a in game.manager.alive()))
                chars, line, start = _probe(view, tile.x, tile.y)
                assert chars == "▀▀", f"纯地形格应为两个半块字符，实际 {chars!r}"
                s0, s1 = _style_at(line, start), _style_at(line, start + 1)
                assert s0.color is not None and s0.bgcolor is not None
                assert s1.color is not None and s1.bgcolor is not None
    asyncio.run(scenario())


def test_unexplored_tile_shows_fog():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                tile = next(t for t in game.world.tiles if not t.explored)
                chars, _, _ = _probe(view, tile.x, tile.y)
                assert chars == "░░"
    asyncio.run(scenario())


def test_settlement_with_agents_merges_count():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                s = game.cities.found(game, game.spawn_x, game.spawn_y, "测试城")
                game.world.tile(s.x, s.y).explored = True
                # 清空城格原有居民，再精确放置 3 人 → ◊3
                for a in list(game.manager.agents_at(s.x, s.y)):
                    a.x, a.y = s.x + 6, s.y
                agents = game.manager.alive()[:3]
                for a in agents:
                    a.x, a.y = s.x, s.y
                chars, _, _ = _probe(view, s.x, s.y)
                assert chars == "◊3", f"定居点+多人应合并为 ◊3，实际 {chars!r}"
                # 只留 1 人 → 仅显示 ◊
                agents[1].x, agents[1].y = s.x + 6, s.y
                agents[2].x, agents[2].y = s.x + 6, s.y
                chars, _, _ = _probe(view, s.x, s.y)
                assert chars == "◊ ", f"定居点+单人应只显示 ◊，实际 {chars!r}"
    asyncio.run(scenario())


def test_settlement_alone_shows_double_diamond():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                s = game.cities.found(game, game.spawn_x, game.spawn_y, "测试城")
                game.world.tile(s.x, s.y).explored = True
                # 把站在城格上的角色移开
                for a in game.manager.agents_at(s.x, s.y):
                    a.x, a.y = s.x + 1, s.y
                chars, _, _ = _probe(view, s.x, s.y)
                assert chars == "◊◊", f"无人的定居点应为 ◊◊，实际 {chars!r}"
    asyncio.run(scenario())


def test_agents_alone_show_at_count():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                tile = next(t for t in game.world.tiles
                            if t.explored and t.terrain == PLAIN
                            and t.resource_amount == 0 and t.settlement_id is None
                            and not any(a.x == t.x and a.y == t.y
                                        for a in game.manager.alive()))
                a1, a2 = game.manager.alive()[:2]
                a1.x, a1.y = tile.x, tile.y
                a2.x, a2.y = tile.x, tile.y
                chars, _, _ = _probe(view, tile.x, tile.y)
                assert chars == "@2", f"多人无定居点应为 @2，实际 {chars!r}"
    asyncio.run(scenario())


def test_single_agent_shows_profession_glyph():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                tile = next(t for t in game.world.tiles
                            if t.explored and t.terrain == PLAIN
                            and t.resource_amount == 0 and t.settlement_id is None
                            and not any(a.x == t.x and a.y == t.y
                                        for a in game.manager.alive()))
                a = game.manager.alive()[0]
                a.x, a.y = tile.x, tile.y
                chars, _, _ = _probe(view, tile.x, tile.y)
                assert chars in set(PROF_ICON.values()) | {"人"}, \
                    f"单人应显示职业汉字，实际 {chars!r}"
    asyncio.run(scenario())


def test_zoom_view_ascii_fallback():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                view.cell_width = 1
                tile = next(t for t in game.world.tiles
                            if t.explored and t.terrain == PLAIN
                            and t.resource_amount == 0 and t.settlement_id is None
                            and not any(a.x == t.x and a.y == t.y
                                        for a in game.manager.alive()))
                # 多人：数字
                a1, a2 = game.manager.alive()[:2]
                a1.x, a1.y = tile.x, tile.y
                a2.x, a2.y = tile.x, tile.y
                chars, _, _ = _probe(view, tile.x, tile.y)
                assert chars == "2", f"缩放视图多人应为数字，实际 {chars!r}"
                # 单人：ASCII 职业字形
                a2.x, a2.y = tile.x + 3, tile.y
                chars, _, _ = _probe(view, tile.x, tile.y)
                assert chars == PROFESSION_GLYPH.get(a1.profession, "@")
    asyncio.run(scenario())


def test_border_bg_kept_with_agents():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                s = game.cities.found(game, game.spawn_x, game.spawn_y, "测试城")
                i = game.cities.settlements.index(s)
                tiles = [t for t in game.world.tiles_in_radius(s.x, s.y, 2)
                         if (t.x, t.y) != (s.x, s.y)]
                t = next(t for t in tiles if t.explored)
                a = game.manager.alive()[0]
                a.x, a.y = t.x, t.y
                chars, line, start = _probe(view, t.x, t.y)
                bg = _style_at(line, start).bgcolor
                assert bg is not None and bg.triplet.hex == BORDER_COLORS[i % len(BORDER_COLORS)], \
                    f"有角色时势力底色应保留 {BORDER_COLORS[i % len(BORDER_COLORS)]}，实际 {bg}"
    asyncio.run(scenario())


def test_render_lines_aligned():
    """宽视图与缩放视图下，渲染输出每行列宽一致（无对齐错位）。"""
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp, settlers=30)   # 更多角色，覆盖 CJK 符号混排
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                view = app.query_one("#map-view")
                for cell_width in (2, 1):
                    view.cell_width = cell_width
                    out = view.render()
                    lines = [l for l in out.split("\n") if l.plain]
                    widths = {l.cell_len for l in lines}
                    assert len(widths) == 1, \
                        f"cell_width={cell_width} 行宽不一致: {widths}"
    asyncio.run(scenario())


def test_spawn_no_overlap():
    """开局殖民者落点互不重叠。"""
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp, settlers=30)
            from collections import Counter
            pos = Counter((a.x, a.y) for a in game.manager.alive() if not a.is_foreign)
            stacked = [p for p, c in pos.items() if c > 1]
            assert not stacked, f"开局殖民者不应同格: {stacked}"
    asyncio.run(scenario())


def test_foreign_npc_scattered():
    """外邦城邦 NPC 散布，每格至多 1 人。"""
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            from collections import Counter
            pos = Counter((a.x, a.y) for a in game.manager.alive() if a.is_foreign)
            stacked = [p for p, c in pos.items() if c > 1]
            assert not stacked, f"外邦 NPC 不应同格: {stacked}"
    asyncio.run(scenario())


def test_scatter_moves_stacked():
    """scatter 把同格多人移到附近空位。"""
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            a1, a2, a3 = game.manager.alive()[:3]
            a1.x, a1.y = a2.x, a2.y = a3.x, a3.y = game.spawn_x, game.spawn_y
            moved = game.manager.scatter(game)
            from collections import Counter
            pos = Counter((a.x, a.y) for a in game.manager.alive())
            stacked = [p for p, c in pos.items() if c > 1]
            assert moved >= 2 and not stacked, f"scatter 应散开同格角色: moved={moved} {stacked}"
    asyncio.run(scenario())


def test_legend_bar_renders():
    """地图下方图例：地形与符号说明齐全，高度足够显示内容。"""
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            game = _make_game(tmp)
            app = MachietyApp(game)
            async with app.run_test(size=(100, 40)) as pilot:
                legend = app.query_one("#map-legend")
                text = legend.render().plain
                for name in ("海洋", "平原", "丘陵", "森林", "山脉", "河流",
                             "定居点", "角色", "迷雾"):
                    assert name in text, f"图例缺少「{name}」: {text!r}"
                # 高度需容纳内容（无边框时 1 行），否则内容被裁剪
                assert legend.size.height >= 1, \
                    f"图例高度不足（内容被裁剪）: {legend.size.height}"
    asyncio.run(scenario())
