"""二维网格世界：自实现 Perlin 噪声生成地形，附带资源分布与战争迷雾。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 地形与资源

OCEAN = "ocean"
PLAIN = "plain"
HILL = "hill"
FOREST = "forest"
MOUNTAIN = "mountain"
RIVER = "river"

TERRAIN_NAMES = {
    OCEAN: "海洋", PLAIN: "平原", HILL: "丘陵",
    FOREST: "森林", MOUNTAIN: "山脉", RIVER: "河流",
}
# 单格渲染字符（双宽格重复一次）
TERRAIN_GLYPH = {
    OCEAN: "~", PLAIN: ".", HILL: "^",
    FOREST: "#", MOUNTAIN: "A", RIVER: "=",
}
TERRAIN_STYLE = {
    OCEAN: "blue", PLAIN: "dim yellow", HILL: "yellow",
    FOREST: "green", MOUNTAIN: "bold white", RIVER: "cyan",
}

FISH = "fish"
WOOD = "wood"
GRAIN = "grain"
HORSE = "horse"
IRON = "iron"
LUXURY = "luxury"

RESOURCE_NAMES = {
    FISH: "鱼群", WOOD: "木材", GRAIN: "谷物",
    HORSE: "马匹", IRON: "铁矿", LUXURY: "奢侈品",
}
RESOURCE_GLYPH = {FISH: "f", WOOD: "t", GRAIN: "w", HORSE: "h", IRON: "i", LUXURY: "$"}
RESOURCE_STYLE = {
    FISH: "bold cyan", WOOD: "bold green", GRAIN: "bold yellow",
    HORSE: "bold magenta", IRON: "bold red", LUXURY: "bold white",
}
FOOD_RESOURCES = {FISH, GRAIN}


# ---------------------------------------------------------------- Perlin 噪声

class Perlin:
    """经典 2D Perlin 梯度噪声，输出约在 [-1, 1]。"""

    def __init__(self, seed: int) -> None:
        rng = random.Random(seed)
        p = list(range(256))
        rng.shuffle(p)
        self.perm = p + p

    @staticmethod
    def _fade(t: float) -> float:
        return t * t * t * (t * (t * 6 - 15) + 10)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + t * (b - a)

    def _grad(self, h: int, x: float, y: float) -> float:
        g = h & 7
        if g < 4:
            return (x if g & 1 == 0 else -x) + (y if g & 2 == 0 else -y)
        return (x if g & 1 == 0 else -x) * 0.5 + (y if g & 2 == 0 else -y) * 0.5

    def noise2(self, x: float, y: float) -> float:
        xi, yi = int(x) & 255, int(y) & 255
        xf, yf = x - int(x), y - int(y)
        u, v = self._fade(xf), self._fade(yf)
        p = self.perm
        aa = p[p[xi] + yi]
        ab = p[p[xi] + yi + 1]
        ba = p[p[xi + 1] + yi]
        bb = p[p[xi + 1] + yi + 1]
        x1 = self._lerp(self._grad(aa, xf, yf), self._grad(ba, xf - 1, yf), u)
        x2 = self._lerp(self._grad(ab, xf, yf - 1), self._grad(bb, xf - 1, yf - 1), u)
        return self._lerp(x1, x2, v) * 0.85

    def fbm(self, x: float, y: float, octaves: int = 4, lacunarity: float = 2.0,
            gain: float = 0.5) -> float:
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += self.noise2(x * freq, y * freq) * amp
            norm += amp
            amp *= gain
            freq *= lacunarity
        return total / norm


# ---------------------------------------------------------------- 地块

@dataclass
class Tile:
    idx: int
    x: int
    y: int
    terrain: str = PLAIN
    resource: str | None = None
    resource_amount: int = 0
    explored: bool = False
    settlement_id: int | None = None
    disaster: str | None = None
    ruins: bool = False          # 奇观烂尾留下的废墟
    elevation: float = 0.0       # 生成高程（由种子重建），用于河流走向
    moisture: float = 0.0        # 生成湿度（由种子重建），渲染层用于群系着色

    @property
    def passable(self) -> bool:
        return self.terrain not in (OCEAN, MOUNTAIN)

    @property
    def food_resource(self) -> bool:
        return self.resource in FOOD_RESOURCES


# ---------------------------------------------------------------- 世界

@dataclass
class World:
    width: int
    height: int
    seed: int
    tiles: list[Tile] = field(default_factory=list)

    # ---------------- 生成

    WORLD_GEN_VERSION = 2      # 存档 meta.world_gen：v1 阈值切分；v2 大陆骨架×群系映射

    @classmethod
    def generate(cls, width: int, height: int, seed: int,
                 version: int | None = None) -> "World":
        """按生成版本创建世界；旧存档用旧算法重建地貌，保持地貌一致。"""
        if version is None or version >= cls.WORLD_GEN_VERSION:
            return cls._generate_v2(width, height, seed)
        return cls._generate_v1(width, height, seed)

    @classmethod
    def _generate_v1(cls, width: int, height: int, seed: int) -> "World":
        """v1：单噪声 + 阈值切分（兼容旧存档地貌）。"""
        world = cls(width=width, height=height, seed=seed)
        rng = random.Random(seed ^ 0x5EED)
        elev = Perlin(seed)
        moist = Perlin(seed ^ 0xC0FFEE)
        scale = 5.5

        tiles: list[Tile] = []
        for y in range(height):
            for x in range(width):
                e = elev.fbm(x / scale, y / scale, octaves=4)
                m = moist.fbm(x / scale + 31.7, y / scale + 17.3, octaves=3)
                # 边缘衰减，让大陆居中
                dx = (x / width - 0.5) * 2
                dy = (y / height - 0.5) * 2
                e -= (dx * dx + dy * dy) * 0.35
                if e < -0.12:
                    terrain = OCEAN
                elif e > 0.42:
                    terrain = MOUNTAIN
                elif e > 0.28:
                    terrain = HILL
                elif m > 0.12:
                    terrain = FOREST
                else:
                    terrain = PLAIN
                tiles.append(Tile(idx=y * width + x, x=x, y=y, terrain=terrain,
                                  elevation=e, moisture=m))
        world.tiles = tiles

        world._carve_rivers_v1(rng, elev, scale)
        world._place_resources(rng)
        return world

    @classmethod
    def _generate_v2(cls, width: int, height: int, seed: int) -> "World":
        """v2：低频大陆骨架×细节地貌 + 海拔×湿度群系映射，大陆连贯、森林成片。"""
        world = cls(width=width, height=height, seed=seed)
        rng = random.Random(seed ^ 0x5EED)
        continent = Perlin(seed ^ 0xC0FFEE)     # 低频大陆骨架（大块大陆）
        detail = Perlin(seed)                    # 中频细节地貌
        moist = Perlin(seed ^ 0x1234ABCD)        # 湿度
        cscale, dscale = 10.0, 5.5

        tiles: list[Tile] = []
        for y in range(height):
            for x in range(width):
                c = continent.fbm(x / cscale, y / cscale, octaves=2)
                d = detail.fbm(x / dscale, y / dscale, octaves=4)
                m = moist.fbm(x / dscale + 31.7, y / dscale + 17.3, octaves=3)
                # 边缘衰减（乘性）：大陆居中，边缘渐沉入海
                dx = (x / width - 0.5) * 2
                dy = (y / height - 0.5) * 2
                edge = 1.0 - (dx * dx + dy * dy) * 0.40
                # 本 Perlin 的 fbm 动态范围仅 ±0.5，需放大拉开地形层次
                e = (c * 0.8 + d * 0.6) * 2.4 * edge - 0.10
                if e < -0.08:
                    terrain = OCEAN
                elif e < 0.15:
                    terrain = FOREST if m > 0.08 else PLAIN    # 低地：湿润成林
                elif e < 0.30:
                    terrain = FOREST if m > 0.25 else HILL     # 高地：湿润林丘
                else:
                    terrain = MOUNTAIN
                tiles.append(Tile(idx=y * width + x, x=x, y=y, terrain=terrain,
                                  elevation=e, moisture=m))
        world.tiles = tiles

        world._carve_rivers_v2(rng)
        world._place_resources(rng)
        return world

    def _carve_rivers_v1(self, rng: random.Random, elev: Perlin, scale: float) -> None:
        """v1 河流：从山脉沿高程贪心下降（兼容旧存档地貌，勿改逻辑）。"""
        mountains = [t for t in self.tiles if t.terrain == MOUNTAIN]
        for _ in range(min(4, max(1, len(mountains) // 12))):
            if not mountains:
                break
            cur = rng.choice(mountains)
            for _step in range(self.width + self.height):
                cands = [n for n in self.neighbors4(cur) if n.terrain != MOUNTAIN]
                if not cands:
                    break
                nxt = min(cands, key=lambda t: t.elevation)
                if nxt.terrain in (OCEAN, RIVER):
                    break          # 入海或汇入已有河流
                if nxt.elevation >= cur.elevation:
                    break          # 到达洼地底部，河流就此终止
                cur = nxt
                cur.terrain = RIVER

    def _carve_rivers_v2(self, rng: random.Random) -> None:
        """v2 河流：从离海的山脉边缘出发，不回头，连续上坡才终止。"""
        mountains = [t for t in self.tiles if t.terrain == MOUNTAIN
                     and any(n.terrain != MOUNTAIN for n in self.neighbors4(t))
                     and not any(n.terrain == OCEAN for n in self.neighbors4(t))]
        for _ in range(min(6, max(1, len(mountains) // 10))):
            if not mountains:
                break
            cur = rng.choice(mountains)
            visited: set[tuple[int, int]] = set()
            up_streak = 0
            for _step in range(self.width + self.height):
                visited.add((cur.x, cur.y))
                cands = [n for n in self.neighbors4(cur)
                         if n.terrain not in (MOUNTAIN, RIVER)
                         and (n.x, n.y) not in visited]
                if not cands:
                    break
                nxt = min(cands, key=lambda t: t.elevation)
                if nxt.terrain == OCEAN:
                    break          # 抵达海岸线
                if nxt.elevation > cur.elevation + 0.02:
                    up_streak += 1
                    if up_streak >= 3:
                        break      # 连续上坡，河流就此终止
                else:
                    up_streak = 0
                cur = nxt
                cur.terrain = RIVER

    def _place_resources(self, rng: random.Random) -> None:
        for t in self.tiles:
            r = rng.random()
            if t.terrain == OCEAN:
                if any(n.terrain != OCEAN for n in self.neighbors4(t)) and r < 0.12:
                    t.resource, t.resource_amount = FISH, rng.randint(40, 120)
            elif t.terrain == FOREST and r < 0.30:
                t.resource, t.resource_amount = WOOD, rng.randint(40, 120)
            elif t.terrain == PLAIN:
                if r < 0.25:
                    t.resource, t.resource_amount = GRAIN, rng.randint(40, 140)
                elif r < 0.30:
                    t.resource, t.resource_amount = HORSE, rng.randint(10, 30)
                elif r < 0.33:
                    t.resource, t.resource_amount = LUXURY, rng.randint(10, 30)
            elif t.terrain == HILL and r < 0.20:
                t.resource, t.resource_amount = IRON, rng.randint(30, 90)
            elif t.terrain == RIVER and r < 0.15:
                t.resource, t.resource_amount = FISH, rng.randint(30, 80)

    # ---------------- 查询

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def tile(self, x: int, y: int) -> Tile | None:
        return self.tiles[y * self.width + x] if self.in_bounds(x, y) else None

    def neighbors4(self, t: Tile) -> list[Tile]:
        out = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = self.tile(t.x + dx, t.y + dy)
            if n:
                out.append(n)
        return out

    def tiles_in_radius(self, x: int, y: int, r: int) -> list[Tile]:
        out = []
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                t = self.tile(x + dx, y + dy)
                if t:
                    out.append(t)
        return out

    def find_spawn(self, rng: random.Random) -> tuple[int, int]:
        """在靠近中心的宜居平原上找一块出生地。"""
        cx, cy = self.width // 2, self.height // 2
        candidates = [t for t in self.tiles
                      if t.terrain in (PLAIN, RIVER)
                      and abs(t.x - cx) + abs(t.y - cy) < max(self.width, self.height) // 3]
        if not candidates:
            candidates = [t for t in self.tiles if t.passable]
        spot = rng.choice(candidates)
        return spot.x, spot.y

    def explored_ratio(self) -> float:
        return sum(1 for t in self.tiles if t.explored) / len(self.tiles)

    # ---------------- 序列化（动态部分，地形由种子重建）

    def dynamic_state(self) -> list[dict]:
        out = []
        for t in self.tiles:
            # 资源被采光（resource_amount==0 且 resource 类型存在）也需保存，
            # 否则读档后 resource_amount 会恢复为初始值
            if t.explored or t.resource_amount or t.settlement_id is not None \
                    or t.disaster or t.ruins or (t.resource is not None and t.resource_amount == 0):
                out.append({
                    "i": t.idx, "e": int(t.explored), "ra": t.resource_amount,
                    "s": t.settlement_id, "d": t.disaster, "r": int(t.ruins),
                })
        return out

    def apply_dynamic_state(self, data: list[dict]) -> None:
        for item in data:
            t = self.tiles[int(item["i"])]
            t.explored = bool(item.get("e"))
            if "ra" in item:
                t.resource_amount = int(item["ra"])
            t.settlement_id = item.get("s")
            t.disaster = item.get("d")
            t.ruins = bool(item.get("r", 0))
