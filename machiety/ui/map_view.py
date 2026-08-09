"""ASCII 世界地图：视口跟随光标、迷雾、单位叠加、缩放、鼠标点击。"""

from __future__ import annotations

import time
import unicodedata

from rich.text import Text, TextType
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from ..agents.agent import PROFESSION_GLYPH
from ..engine.world import (OCEAN, PLAIN, RESOURCE_STYLE, TERRAIN_GLYPH,
                            TERRAIN_STYLE)

FLASH_DURATION = 2.0     # 战斗闪烁持续秒数

# 单角色地块按职业显示（宽视图汉字，缩放视图回退 ASCII）
PROF_ICON = {
    "farmer": "农", "hunter": "猎", "fisher": "渔", "artisan": "匠",
    "merchant": "商", "soldier": "兵", "official": "官",
    "priest": "祭", "scholar": "学",
}
# 定居点势力范围底色（按建城顺序轮转）
BORDER_COLORS = ["#0d2b45", "#14331f", "#3a2413", "#2e1a3a"]

# 像素风地形色板：地形 -> (左上, 右上, 左下, 右下) 四角色值（每格 2×2 像素）
PIXEL_PALETTE = {
    "ocean": ("#0a1e3a", "#0d2547", "#122c52", "#0d2547"),
    "plain": ("#486a30", "#52743a", "#3c5a28", "#44642c"),
    "hill": ("#75642e", "#7f6e34", "#5f5226", "#695a2a"),
    "forest": ("#245024", "#2d5f2d", "#1a3d1a", "#1f471f"),
    "mountain": ("#a0a0b0", "#b4b4c4", "#7c7c8c", "#8c8c9c"),
    "river": ("#2e7484", "#3e94a6", "#215a68", "#296878"),
}
FOG_COLOR = "#0c1018"              # 迷雾底色
TRAIL_FG, TRAIL_BG = "#5a5a5a", "#2b2b2b"   # 移动拖影像素色
# 平原按湿度两套色板：干燥偏黄 / 湿润偏绿（v2 群系下干燥平原最常见）
PLAIN_DRY = ("#6d6430", "#776c38", "#5c5428", "#665c2e")
PLAIN_WET = ("#3f6a30", "#4a7538", "#345828", "#3d632c")


def _shade(hex_color: str, factor: float) -> str:
    """按比例调亮/调暗 hex 颜色。"""
    r = max(0, min(255, int(int(hex_color[1:3], 16) * factor)))
    g = max(0, min(255, int(int(hex_color[3:5], 16) * factor)))
    b = max(0, min(255, int(int(hex_color[5:7], 16) * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _tile_pixels(tile) -> tuple[str, str, str, str]:
    """按地形/海拔/湿度取四角色值：海洋分浅滩层次，平原随湿度偏黄或偏绿。"""
    base = PLAIN_WET if tile.moisture > 0.08 else PLAIN_DRY \
        if tile.terrain == PLAIN else PIXEL_PALETTE[tile.terrain]
    e = tile.elevation
    if tile.terrain == OCEAN:
        if e > -0.06:
            return tuple(_shade(c, 1.35) for c in base)   # 浅滩：亮
        if e < -0.20:
            return tuple(_shade(c, 0.75) for c in base)   # 深海：暗
        return base
    if e > 0.15:
        return tuple(_shade(c, 1.25) for c in base)
    if e < -0.15:
        return tuple(_shade(c, 0.8) for c in base)
    return base


def _char_width(ch: str) -> int:
    """终端列宽：CJK/全角字符占 2 列。"""
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def _fit_cell(text: str, width: int) -> str:
    """截断或补齐空格，使文本恰好占 width 列，保证网格对齐。"""
    out, used = "", 0
    for ch in text:
        w = _char_width(ch)
        if used + w > width:
            break
        out += ch
        used += w
    return out + " " * (width - used)


class MapView(Widget):
    """渲染游戏世界；光标与缩放由 App 的按键动作驱动。"""

    class TileClicked(Message):
        """点击了界内的一个地块，由 App 决定追踪语义。"""

        def __init__(self, x: int, y: int) -> None:
            self.x, self.y = x, y
            super().__init__()

    DEFAULT_CSS = """
    MapView { background: $surface; }
    """

    def __init__(self, game, **kwargs) -> None:
        super().__init__(**kwargs)
        self.game = game
        self.border_title = "Machiety 大陆"
        self.cursor_x, self.cursor_y = game.spawn_x, game.spawn_y
        self.cell_width = 2          # 缩放：2 或 1 字符/格
        self.city_mode = False
        self.flashes: dict[tuple[int, int], float] = {}   # 位置 -> 触发时间
        self.dirty = True            # 节流刷新：仅光标移动/事件触发时重绘

    # ---------------- 光标与交互

    def move_cursor(self, dx: int, dy: int) -> None:
        self.cursor_x = max(0, min(self.game.world.width - 1, self.cursor_x + dx))
        self.cursor_y = max(0, min(self.game.world.height - 1, self.cursor_y + dy))
        self.dirty = True
        self.refresh()

    def toggle_zoom(self) -> None:
        self.cell_width = 1 if self.cell_width == 2 else 2
        self.dirty = True
        self.refresh()

    def toggle_mode(self) -> None:
        self.city_mode = not self.city_mode
        self.dirty = True
        self.refresh()

    def add_flash(self, x: int, y: int) -> None:
        self.flashes[(x, y)] = time.monotonic()
        self.dirty = True

    def on_click(self, event: Click) -> None:
        """鼠标点击：光标跳到点击的地块，并通知 App 处理追踪。"""
        x0, y0, _, _ = self._viewport()
        # Click.offset 以组件外沿（含边框）为原点，渲染内容从 content_offset
        # 开始，必须先扣除，否则会整体偏移一格（点角色上方一格才命中）
        cx, cy = self.content_offset
        x = x0 + (event.offset.x - cx) // self.cell_width
        y = y0 + (event.offset.y - cy)
        if self.game.world.in_bounds(x, y):
            self.cursor_x, self.cursor_y = x, y
            self.refresh()
            self.post_message(self.TileClicked(x, y))

    def _viewport(self) -> tuple[int, int, int, int]:
        """返回视口 (x0, y0, cols, rows)，以光标为中心。"""
        world = self.game.world
        try:
            cols, rows = self.size.width // self.cell_width, self.size.height
        except Exception:
            cols, rows = 40, 20
        cols, rows = max(8, cols), max(4, rows)
        x0 = max(0, min(self.cursor_x - cols // 2, world.width - cols))
        y0 = max(0, min(self.cursor_y - rows // 2, world.height - rows))
        return x0, y0, cols, rows

    # ---------------- 渲染

    def render(self) -> TextType:
        world = self.game.world
        x0, y0, cols, rows = self._viewport()

        settlements = {s.id: s for s in self.game.cities.settlements}
        agents_by_pos: dict[tuple[int, int], list] = {}
        trails: set[tuple[int, int]] = set()
        for a in self.game.manager.alive():
            agents_by_pos.setdefault((a.x, a.y), []).append(a)
            if a.prev_x is not None and (a.prev_x, a.prev_y) != (a.x, a.y):
                trails.add((a.prev_x, a.prev_y))

        # 定居点势力范围（半径2）
        borders: dict[tuple[int, int], int] = {}
        for i, s in enumerate(self.game.cities.settlements):
            for t in self.game.world.tiles_in_radius(s.x, s.y, 2):
                if (t.x, t.y) != (s.x, s.y):
                    borders.setdefault((t.x, t.y), i)

        now = time.monotonic()
        self.flashes = {p: t for p, t in self.flashes.items() if now - t < FLASH_DURATION}
        unrest_blink = self.game.policy.unrest > 30 and int(now * 2) % 2 == 0

        disaster_flash = {"flood": "bold blue", "plague": "bold magenta",
                          "locust": "bold red", "drought": "bold yellow"}
        output = Text(no_wrap=True)
        for y in range(y0, min(world.height, y0 + rows)):
            for x in range(x0, min(world.width, x0 + cols)):
                tile = world.tiles[y * world.width + x]
                self._append_cell(output, tile, x, y, settlements=settlements,
                                  agents_by_pos=agents_by_pos, trails=trails,
                                  borders=borders, flashes=self.flashes,
                                  unrest_blink=unrest_blink,
                                  disaster_flash=disaster_flash)
            output.append("\n")
        return output

    # ---------------- 单格渲染

    @staticmethod
    def _agent_style(base: str, here: list) -> str:
        """角色样式：外邦青色优先，其次先知品红。"""
        if any(a.is_foreign for a in here):
            return "bold cyan"
        if any(a.prophet for a in here):
            return "bold magenta"
        return base

    def _emit(self, output, cell: str, style: str, *, is_cursor: bool,
              flash: bool, width: int | None = None,
              border_bg: str | None = None, blink: bool = False) -> None:
        """追加一个统一样式格；可附加势力底色、动荡闪烁与光标反显。"""
        width = width or self.cell_width
        if border_bg:
            style += f" on {border_bg}"
        if blink:
            style += " reverse"
        if flash:
            style = "bold red reverse"
        elif is_cursor:
            style += " reverse"
        output.append(_fit_cell(cell, width), style)

    def _emit_pixels(self, output, fg_l: str, fg_r: str, bg_l: str, bg_r: str,
                     *, is_cursor: bool, flash: bool,
                     border_bg: str | None = None, blink: bool = False) -> None:
        """追加 2 列半块像素：左列 = 左上/左下色，右列 = 右上/右下色。"""
        style_l = f"{fg_l} on {bg_l}"
        style_r = f"{fg_r} on {bg_r}"
        if border_bg:
            style_l = f"{fg_l} on {border_bg}"
            style_r = f"{fg_r} on {border_bg}"
        if blink:
            style_l += " reverse"
            style_r += " reverse"
        if flash:
            style_l = style_r = "bold red reverse"
        elif is_cursor:
            style_l += " reverse"
            style_r += " reverse"
        output.append("▀", style_l)
        output.append("▀", style_r)

    def _append_cell(self, output, tile, x: int, y: int, *, settlements,
                     agents_by_pos, trails, borders, flashes,
                     unrest_blink: bool, disaster_flash) -> None:
        """追加一个格子：宽视图 2 列（像素地形/符号合并），缩放视图 1 列 ASCII。"""
        is_cursor = (x == self.cursor_x and y == self.cursor_y)
        flash = (x, y) in flashes
        if not tile.explored:
            self._emit(output, "░" * self.cell_width, f"dim white on {FOG_COLOR}",
                       is_cursor=is_cursor, flash=flash)
            return
        here = agents_by_pos.get((x, y), [])
        s = settlements.get(tile.settlement_id)
        border = borders.get((x, y))
        border_bg = (BORDER_COLORS[border % len(BORDER_COLORS)]
                     if border is not None else None)
        blink = border is not None and unrest_blink
        wide = self.cell_width == 2

        if s is not None and here and wide:
            # 定居点 + 角色：≥2 人合并显示 ◊N，单人只显示 ◊（外邦/先知色沿用角色规则）
            n = len(here)
            cell = f"◊{n}" if n >= 2 else "◊"
            style = "bold green" if s.building else "bold red"
            self._emit(output, cell, self._agent_style(style, here),
                       is_cursor=is_cursor, flash=flash,
                       border_bg=border_bg, blink=blink)
        elif here and wide:
            # 国民叠加：单人按职业图标，多人 @数量
            if len(here) == 1:
                cell = PROF_ICON.get(here[0].profession, "人")
            else:
                cell = f"@{len(here)}" if len(here) < 10 else "@+"
            self._emit(output, cell, self._agent_style("bold yellow", here),
                       is_cursor=is_cursor, flash=flash,
                       border_bg=border_bg, blink=blink)
        elif here:
            # 缩放视图：多人数字，单人 ASCII 职业字形
            cell = (str(len(here)) if len(here) > 1
                    else PROFESSION_GLYPH.get(here[0].profession, "@"))
            self._emit(output, cell, self._agent_style("bold yellow", here),
                       is_cursor=is_cursor, flash=flash, width=1,
                       border_bg=border_bg, blink=blink)
        elif s is not None:
            cell = "◊" * self.cell_width
            style = "bold green" if s.building else "bold red"
            if self.city_mode:
                style += " reverse"
            self._emit(output, cell, style, is_cursor=is_cursor, flash=flash,
                       border_bg=border_bg, blink=blink)
        elif wide and (x, y) in trails:
            # 移动拖影：旧位置像素灰化
            self._emit_pixels(output, TRAIL_FG, TRAIL_FG, TRAIL_BG, TRAIL_BG,
                              is_cursor=is_cursor, flash=flash,
                              border_bg=border_bg, blink=blink)
        elif wide:
            # 像素地形：2×2 半块；资源/废墟/灾难叠加在像素色上
            tl, tr, bl, br = _tile_pixels(tile)
            fg_l, fg_r = tl, tr
            if tile.ruins:
                fg_l = fg_r = "dim #8a7f72"
            elif tile.resource and tile.resource_amount > 0:
                fg_l = RESOURCE_STYLE[tile.resource]
            if tile.disaster:
                fg_l = fg_r = disaster_flash.get(tile.disaster, fg_l)
            self._emit_pixels(output, fg_l, fg_r, bl, br,
                              is_cursor=is_cursor, flash=flash,
                              border_bg=border_bg, blink=blink)
        else:
            # 缩放视图：ASCII 地形/废墟/灾难/拖影
            cell = TERRAIN_GLYPH[tile.terrain]
            style = TERRAIN_STYLE[tile.terrain]
            if tile.ruins:
                cell, style = "▚", "dim #8a7f72"
            if tile.disaster:
                style = disaster_flash.get(tile.disaster, style)
            if (x, y) in trails:
                style = "dim #5a5a5a"
            self._emit(output, cell, style, is_cursor=is_cursor, flash=flash,
                       width=1, border_bg=border_bg, blink=blink)

    # ---------------- 光标处信息

    def cursor_info(self) -> str:
        world = self.game.world
        tile = world.tile(self.cursor_x, self.cursor_y)
        if tile is None:
            return ""
        if not tile.explored:
            return f"({tile.x},{tile.y}) 迷雾笼罩之地"
        from ..engine.world import RESOURCE_NAMES, TERRAIN_NAMES
        lines = [f"地块（{tile.x},{tile.y}） {TERRAIN_NAMES[tile.terrain]}"]
        if tile.resource and tile.resource_amount > 0:
            lines.append(f"资源：{RESOURCE_NAMES[tile.resource]} ×{tile.resource_amount}")
        if tile.settlement_id is not None:
            s = next((x for x in self.game.cities.settlements if x.id == tile.settlement_id), None)
            if s:
                lines.append(self.game.cities.describe(self.game, s))
        here = self.game.manager.agents_at(tile.x, tile.y)
        if here:
            lines.append("此地国民：")
            for a in here[:6]:
                mark = "★" if a.great_title else ""
                if a.prophet:
                    mark += "☀"
                if a.is_foreign:
                    mark += "◇"
                rel = ""
                if a.relations:
                    best = max(a.relations, key=a.relations.get)
                    if a.relations[best] >= 3:
                        rel += f" 至交:{best}"
                    worst = min(a.relations, key=a.relations.get)
                    if a.relations[worst] <= -3:
                        rel += f" 宿敌:{worst}"
                lines.append(f"  {mark}{a.name}（{a.profession_name}，{a.age}岁）{rel}")
            if len(here) > 6:
                lines.append(f"  …另有 {len(here) - 6} 人")
        return "\n".join(lines)
