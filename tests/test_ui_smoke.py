"""UI 冒烟：Textual 应用挂载、地图渲染、指令执行、命令历史。"""

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


def test_ui_smoke():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            app = MachietyApp(_make_game(tmp))
            async with app.run_test(size=(120, 36)) as pilot:
                await pilot.pause()
                # 状态栏与地图已渲染
                assert app.query_one("#status-bar") is not None
                assert app.query_one("#map-view") is not None
                # 冻结时间，保证断言确定性（先移开焦点，避免空格被输入框吃掉）
                app.set_focus(None)
                await pilot.press("space")
                # 光标移动与详情查看
                await pilot.press("right", "down")
                await pilot.press("enter")
                # w 追踪光标处角色
                agent = app.game.manager.alive()[0]
                view = app.query_one("#map-view")
                view.cursor_x, view.cursor_y = agent.x, agent.y
                await pilot.press("w")
                await pilot.pause()
                assert app.game.watched == agent.name
                # 命令栏执行指令
                bar = app.query_one("#command-bar")
                bar.focus()
                await pilot.pause()
                bar.value = "epoch"
                await pilot.press("enter")
                await pilot.pause()
                assert "时代" in app.last_result
                # 命令历史：上箭头召回上一条指令
                bar.value = ""
                await pilot.press("up")
                await pilot.pause()
                assert bar.value == "epoch"
                await pilot.press("down")
                await pilot.pause()
                assert bar.value == ""
                # 神谕指令
                bar.value = 'miracle "雨水将赐福此地"'
                await pilot.press("enter")
                await pilot.pause()
                assert "神谕" in app.last_result
                # 存档指令
                bar.value = "save smoke"
                await pilot.press("enter")
                await pilot.pause()
                assert "已存档" in app.last_result
            await app.game.llm.close()

    asyncio.run(scenario())
