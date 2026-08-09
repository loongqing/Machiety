"""存档读写：单文件多槽位存档库（saves/saves.db），兼容旧版单文件存档。

v3 起所有存档集中在 saves/saves.db 一个文件中，按名称存取槽位，
自动存档滚动覆盖同一槽位，不再产生大量零散 .db 文件。
旧版 saves/<名称>.db 存档仍可按名读取（legacy 路径），只读不再写入。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..config import GameConfig
from ..engine.scheduler import Game
from ..llm.base import BaseLLM
from .db import open_db

SCHEMA_VERSION = 4          # v4：反应链/祈愿板/灾难会议状态
SLOT_DB_NAME = "saves.db"   # 存档库文件名


class SaveVersionError(Exception):
    """存档版本高于当前程序支持的版本，无法读取。"""


def slot_db_path(config: GameConfig) -> Path:
    return Path(config.save_dir) / SLOT_DB_NAME


def _legacy_path(config: GameConfig, name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "save"
    return Path(config.save_dir) / f"{safe}.db"


def _save_summary(game: Game) -> dict:
    """选单展示用的轻量摘要。"""
    st = game.stats()
    return {"progress": game.clock.date_str, "era": st["era"],
            "population": st["population"], "seed": game.seed}


def _check_version(conn, name: str) -> None:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    version = int(row[0]) if row else 1
    if version > SCHEMA_VERSION:
        raise SaveVersionError(
            f"存档「{name}」为 v{version}，当前程序仅支持到 v{SCHEMA_VERSION}，"
            "请升级游戏后再读取")


# ---------------- 单文件槽位存取（v3）

def save_game(game: Game, name: str) -> Path:
    """命名存档：写入/覆盖单文件存档库中的槽位。"""
    data = game.to_save_dict()
    path = slot_db_path(game.config)
    conn = open_db(path)
    try:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
        conn.execute("DELETE FROM save_slots WHERE name=?", (name,))
        conn.execute(
            "INSERT INTO save_slots(name, updated_at, summary, data) VALUES (?, ?, ?, ?)",
            (name, datetime.now().strftime("%Y-%m-%d %H:%M"),
             json.dumps(_save_summary(game), ensure_ascii=False),
             json.dumps(data, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    return path


def load_game(name: str, config: GameConfig, llm: BaseLLM) -> Game:
    """按名称读档：先查存档库槽位，未命中则回退旧版 .db 文件。"""
    path = slot_db_path(config)
    if path.exists():
        conn = open_db(path)
        try:
            _check_version(conn, name)
            row = conn.execute("SELECT data FROM save_slots WHERE name=?", (name,)).fetchone()
        finally:
            conn.close()
        if row:
            game = Game.from_save_dict(config, llm, json.loads(row[0]))
            game.current_slot = name
            return game
    legacy = _legacy_path(config, name)
    if legacy.exists():
        game = _load_legacy(legacy, name, config, llm)
        game.current_slot = name
        return game
    raise FileNotFoundError(name)


def list_slots(config: GameConfig) -> list[dict]:
    """存档库全部槽位，最近更新在前。"""
    path = slot_db_path(config)
    if not path.exists():
        return []
    conn = open_db(path)
    try:
        rows = conn.execute(
            "SELECT name, updated_at, summary FROM save_slots "
            "ORDER BY updated_at DESC, name").fetchall()
    finally:
        conn.close()
    slots = []
    for name, updated_at, summary in rows:
        try:
            info = json.loads(summary)
        except (json.JSONDecodeError, TypeError):
            info = {}
        slots.append({"name": name, "updated_at": updated_at, "info": info})
    return slots


def delete_save(config: GameConfig, name: str) -> bool:
    """删除一个槽位，返回是否删除成功。"""
    path = slot_db_path(config)
    if not path.exists():
        return False
    conn = open_db(path)
    try:
        cur = conn.execute("DELETE FROM save_slots WHERE name=?", (name,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_saves(config: GameConfig) -> list[str]:
    """可载入的存档名：槽位 + 旧版文件（供 load 失败时提示）。"""
    names = [s["name"] for s in list_slots(config)]
    d = Path(config.save_dir)
    if d.exists():
        for p in sorted(d.glob("*.db")):
            if p.name != SLOT_DB_NAME and p.stem not in names:
                names.append(p.stem)
    return names


# ---------------- 旧版单文件存档（v1/v2，只读）

def _load_legacy(path: Path, name: str, config: GameConfig, llm: BaseLLM) -> Game:
    conn = open_db(path)
    try:
        def meta(key: str, default):
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

        # 版本检查：旧档缺省字段走默认值可读；更新的存档无法兼容
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        version = int(row[0]) if row else 1
        if version > SCHEMA_VERSION:
            raise SaveVersionError(
                f"存档「{name}」为 v{version}，当前程序仅支持到 v{SCHEMA_VERSION}，"
                "请升级游戏后再读取")
        data = {
            "meta": meta("save", {}),
            "clock": meta("clock", {"total_hours": 0}),
            "watched": meta("watched", None),
            "disasters": meta("disasters", []),
            "agents": [json.loads(r[0]) for r in conn.execute("SELECT data FROM agents")],
            "world_dynamic": [
                {"i": r[0], "e": r[1], "ra": r[2], "s": r[3], "d": r[4], "r": r[5]}
                for r in conn.execute(
                    "SELECT idx, explored, amount, settlement, disaster, ruins FROM tiles_dynamic")
            ],
        }
        for key in ("tech", "policy", "cities", "great", "wonders", "epoch"):
            row = conn.execute("SELECT data FROM civ WHERE key=?", (key,)).fetchone()
            data[key] = json.loads(row[0]) if row else {}
        data["chronicle"] = [
            {"tick": r[0], "kind": r[1], "text": r[2], "x": r[3], "y": r[4],
             "data": json.loads(r[5]) if r[5] else {}}
            for r in conn.execute("SELECT tick, kind, text, x, y, data FROM chronicle ORDER BY tick")
        ]
    finally:
        conn.close()
    return Game.from_save_dict(config, llm, data)
