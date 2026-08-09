"""CLI 入口：python -m machiety [--headless] [--days N] [--seed S] [--config PATH] [--load NAME]
[--speed MS] [--population N] [--economy]"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Windows 终端默认 GBK，无法渲染地图字符，统一切到 UTF-8
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

from .config import load_config
from .engine.scheduler import Game
from .llm.base import BaseLLM
from .llm.mock import MockLLM

console = Console()


def build_llm(config, seed: int) -> BaseLLM:
    mock = MockLLM(seed=seed)
    if config.llm.available:
        from .llm.openai_client import OpenAIChat
        console.print(f"[green]LLM 已连接[/green]：{config.llm.base_url}（{config.llm.model}）")
        return OpenAIChat(config.llm, fallback=mock, seed=seed)
    console.print("[yellow]未检测到 LLM 配置，使用离线 MockLLM（复制 config.toml.example 为 config.toml 可接入真实模型）[/yellow]")
    return mock


def build_game(config, llm: BaseLLM, seed: int | None = None) -> Game:
    game = Game(config, llm, seed=seed)
    game.spawn_settlers()
    return game


def render_headless_map(game: Game, width: int = 48) -> str:
    from .engine.world import TERRAIN_GLYPH
    lines = []
    for y in range(min(game.world.height, 24)):
        row = []
        for x in range(min(game.world.width, width)):
            t = game.world.tile(x, y)
            if not t.explored:
                row.append("░")
            elif any(a.x == x and a.y == y for a in game.manager.alive()):
                row.append("@")
            elif t.settlement_id is not None:
                row.append("◊")
            else:
                row.append(TERRAIN_GLYPH[t.terrain])
        lines.append("".join(row))
    return "\n".join(lines)


async def run_headless(game: Game, days: int) -> int:
    console.print(Panel("[bold]Machiety[/bold] 无头模拟模式", subtitle=f"种子 {game.seed}"))
    console.print(Panel(render_headless_map(game), title="初始大陆（已探索区域）"))

    for d in range(days):
        for _ in range(24):
            await game.step()
        st = game.stats()
        events_today = [e for e in game.bus.log if d * 24 <= e.tick < (d + 1) * 24]
        highlights = [e.text for e in events_today
                      if e.kind in ("epiphany", "policy", "era", "wonder", "great_person",
                                    "city", "rebellion", "disaster")][:3]
        line = (f"第{d + 1}日  人口{st['population']:>3}  存粮{st['food_stock']:>7.0f}  "
                f"技术{st['techs']}  定居点{st['settlements']}  {st['era']}时代")
        console.print(line)
        for h in highlights:
            console.print(f"   [cyan]✦ {h}[/cyan]")

    # 终局报告
    st = game.stats()
    table = Table(title="模拟报告")
    table.add_column("指标"), table.add_column("数值")
    table.add_row("最终人口", str(st["population"]))
    table.add_row("定居点", str(st["settlements"]))
    table.add_row("已发明技术", "、".join(t.name for t in game.tech.techs) or "无")
    table.add_row("生效政策", "、".join(p.name for p in game.policy.active.values() if p) or "无")
    table.add_row("时代", st["era"])
    table.add_row("已探索", f"{game.world.explored_ratio():.0%}")
    table.add_row("LLM 调用", f"{game.llm.calls} 次（降级 {getattr(game.llm, 'fallbacks', 0)}）")
    console.print(table)
    return 0


def choose_startup_save(config) -> tuple[str | None, str]:
    """启动时交互式选择存档：返回 (要载入的存档名, 新存档命名)。"""
    from .persistence.saver import delete_save, list_slots

    while True:
        console.print(Panel("[bold]Machiety[/bold] · 文明的起点",
                            subtitle="选择你的历史，或开辟新世界"))
        slots = list_slots(config)
        if not slots:
            new_name = console.input("[bold]尚无存档。为新存档命名（直接回车=autosave）：[/bold]").strip()
            return None, new_name
        table = Table(title="现有存档")
        table.add_column("#", justify="right")
        table.add_column("存档")
        table.add_column("进度")
        table.add_column("更新于")
        for i, s in enumerate(slots, 1):
            info = s["info"]
            table.add_row(str(i), s["name"],
                          f"{info.get('progress', '')} · {info.get('era', '')}时代 · "
                          f"人口{info.get('population', '?')}",
                          s["updated_at"])
        console.print(table)
        choice = console.input(
            "[bold]输入序号或名称载入存档，N 新建世界，D 删除存档 >[/bold] ").strip()

        if choice.lower() in ("n", "new", "新建", ""):
            new_name = console.input("[bold]为新存档命名（直接回车=autosave）：[/bold]").strip()
            return None, new_name
        if choice.lower() in ("d", "delete", "删除"):
            _delete_from_menu(config, slots)
            continue    # 删除后刷新列表重新选择
        if choice.isdigit() and 1 <= int(choice) <= len(slots):
            return slots[int(choice) - 1]["name"], ""
        return choice, ""


def _delete_from_menu(config, slots: list[dict]) -> None:
    """启动选单中的删除流程：选择目标 → 两次确认。"""
    from .persistence.saver import delete_save

    target = console.input("[bold red]输入要删除的存档序号或名称 >[/bold red] ").strip()
    # 解析目标名称
    if target.isdigit() and 1 <= int(target) <= len(slots):
        name = slots[int(target) - 1]["name"]
    else:
        name = target
    if not name:
        console.print("[dim]未指定目标，已取消[/dim]")
        return
    # 第一次确认
    confirm1 = console.input(f"[yellow]确定要删除存档「{name}」吗？(y/N) >[/yellow] ").strip()
    if confirm1.lower() not in ("y", "yes"):
        console.print("[dim]已取消删除[/dim]")
        return
    # 第二次确认（不可撤销警告）
    confirm2 = console.input(
        f"[bold red]此操作不可撤销！再次确认删除「{name}」？(y/N) >[/bold red] ").strip()
    if confirm2.lower() not in ("y", "yes"):
        console.print("[dim]已取消删除[/dim]")
        return
    if delete_save(config, name):
        console.print(f"[green]存档「{name}」已删除[/green]")
    else:
        console.print(f"[red]找不到存档「{name}」[/red]")


def acquire_game(config, llm: BaseLLM, seed: int | None, args) -> Game:
    """决定本次进入的世界：--load / --new / 启动选单 / 直接新开。"""
    from .persistence.saver import SaveVersionError, load_game, save_game

    def load_or_exit(name: str) -> Game:
        try:
            g = load_game(name, config, llm)
        except FileNotFoundError:
            console.print(f"[red]找不到存档「{name}」[/red]")
            raise SystemExit(1)
        except SaveVersionError as e:
            console.print(f"[red]存档无法载入：{e}[/red]")
            raise SystemExit(1)
        console.print(f"[green]已载入存档「{name}」[/green]")
        return g

    if args.load:
        return load_or_exit(args.load)
    if args.headless:
        return build_game(config, llm, seed=seed)
    if args.new is not None:                    # --new [名称]：跳过选单直接新开
        game = build_game(config, llm, seed=seed)
        slot = args.new or "autosave"
        game.current_slot = slot
        save_game(game, slot)                   # 新建即自动保存
        console.print(f"[green]新存档「{slot}」已创建并自动保存[/green]")
        return game
    if not sys.stdin.isatty():                  # 非交互环境直接新开
        return build_game(config, llm, seed=seed)
    try:
        load_name, new_name = choose_startup_save(config)
    except EOFError:                            # 输入流异常时兜底新开
        return build_game(config, llm, seed=seed)
    if load_name:
        return load_or_exit(load_name)
    game = build_game(config, llm, seed=seed)
    slot = new_name or "autosave"
    game.current_slot = slot
    save_game(game, slot)                       # 新建即自动保存
    console.print(f"[green]新存档「{slot}」已创建并自动保存[/green]")
    return game


def _save_quietly(get_game) -> None:
    """退出兜底：无论以何种方式结束，都静默自动存档一次，任何异常均吞掉。"""
    try:
        from .persistence.saver import save_game
        game = get_game()
        name = game.current_slot or "autosave"
        save_game(game, name)
        console.print(f"[green]退出时已自动存档「{name}」[/green]")
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="machiety", description="Machiety 虚拟国家模拟")
    parser.add_argument("--headless", action="store_true", help="无头文本模式（不进 Textual UI）")
    parser.add_argument("--days", type=int, default=5, help="无头模式模拟天数")
    parser.add_argument("--seed", type=int, default=None, help="世界种子")
    parser.add_argument("--config", default="config.toml", help="配置文件路径")
    parser.add_argument("--load", default=None, help="读取存档名")
    parser.add_argument("--new", nargs="?", const="", default=None,
                        help="跳过启动选单直接新开（可选：为新存档命名）")
    parser.add_argument("--speed", type=int, default=None,
                        help="UI tick 间隔毫秒（覆盖默认 350ms）")
    parser.add_argument("--population", type=int, default=None,
                        help="开局殖民者人数（覆盖 config settlers）")
    parser.add_argument("--economy", action="store_true",
                        help="LLM 节流模式（规划缓存 + 分组反思）")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.population is not None:
        config.settlers = max(1, args.population)
    if args.economy:
        config.llm.economy = True
    seed = args.seed if args.seed is not None else config.seed
    llm = build_llm(config, seed or 20260807)

    game = acquire_game(config, llm, seed, args)

    if args.headless:
        atexit.register(_save_quietly, lambda: game)
        raise SystemExit(asyncio.run(run_headless(game, args.days)))

    from .ui.app import MachietyApp, TICK_SECONDS
    tick_seconds = (args.speed / 1000.0) if args.speed is not None else TICK_SECONDS
    app = MachietyApp(game, tick_seconds=max(0.02, tick_seconds))
    # UI 模式不注册 atexit：quit/exit 指令和 Ctrl+Q 均已在 action_quit 中保存，
    # 避免退出时重复写入同一槽位
    app.run()


if __name__ == "__main__":
    main()
