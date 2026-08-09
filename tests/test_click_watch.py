"""UI：地图点击等价 watch——点角色追踪角色、点定居点追踪定居点、点空地取消追踪。"""

import asyncio
import tempfile

from machiety.config import GameConfig
from machiety.engine.scheduler import Game
from machiety.llm.mock import MockLLM
from machiety.ui.app import MachietyApp


def _make_game(save_dir: str) -> Game:
    config = GameConfig(seed=7, width=32, height=24, settlers=10, save_dir=save_dir)
    game = Game(config, MockLLM(seed=7), seed=7)
    game.spawn_settlers()
    return game


async def _click_tile(pilot, app, x: int, y: int) -> None:
    """按地块在屏幕上的真实位置点击（含边框偏移），而非靠映射公式推算。"""
    view = app.query_one("#map-view")
    view.cursor_x, view.cursor_y = x, y
    view.dirty = True
    await pilot.pause()
    x0, y0, _, _ = view._viewport()
    screen_x = view.region.x + view.content_offset.x + (x - x0) * view.cell_width
    screen_y = view.region.y + view.content_offset.y + (y - y0)
    await pilot.click(app.screen, offset=(screen_x, screen_y))
    await pilot.pause()


def test_click_watch():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            app = MachietyApp(_make_game(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                app.set_focus(None)
                await pilot.press("space")   # 冻结时间，保证断言确定性

                # 点击有角色的地块 -> 等价 watch <角色名>
                agent = app.game.manager.alive()[0]
                await _click_tile(pilot, app, agent.x, agent.y)
                assert app.game.watched == agent.name
                assert app._panel_follow_watch is True

                # 点击定居点（中心无角色）-> 等价 watch <定居点名>
                s = app.game.cities.found(app.game, 2, 2)
                assert not app.game.manager.agents_at(2, 2)
                await _click_tile(pilot, app, 2, 2)
                assert app.game.watched == s.name
                assert app._panel_follow_watch is True

                # 点击无角色无定居点的空地 -> 等价 watch（取消追踪）
                empty = next(
                    t for t in app.game.world.tiles
                    if not app.game.manager.agents_at(t.x, t.y)
                    and t.settlement_id is None and (t.x, t.y) != (2, 2))
                empty.explored = True
                await _click_tile(pilot, app, empty.x, empty.y)
                assert app.game.watched is None
                assert app._panel_follow_watch is False
            await app.game.llm.close()

    asyncio.run(scenario())
