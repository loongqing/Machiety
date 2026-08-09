"""地图图例：地形色块与关键符号说明。"""

from __future__ import annotations

from textual.widgets import Static

from .map_view import PLAIN_DRY, PIXEL_PALETTE

# 地形图例：色块颜色与地图渲染共用同一调色板（平原取最常见的干燥色）
_TERRAIN_ITEMS = [
    ("ocean", PIXEL_PALETTE["ocean"][0], "海洋"),
    ("plain", PLAIN_DRY[0], "平原"),
    ("hill", PIXEL_PALETTE["hill"][0], "丘陵"),
    ("forest", PIXEL_PALETTE["forest"][0], "森林"),
    ("mountain", PIXEL_PALETTE["mountain"][0], "山脉"),
    ("river", PIXEL_PALETTE["river"][0], "河流"),
]


class LegendBar(Static):
    """地图下方一行图例：▀ 色块 + 地形名，与地图渲染同源配色。"""

    def compose_legend(self) -> str:
        parts = [f"[{color}]▀[/] {name}" for _, color, name in _TERRAIN_ITEMS]
        parts.append("[bold red]◊[/] 定居点")
        parts.append("[bold yellow]@[/] 角色")
        parts.append("[dim white]░[/] 迷雾")
        return "   ".join(parts)

    def on_mount(self) -> None:
        self.update(self.compose_legend())
