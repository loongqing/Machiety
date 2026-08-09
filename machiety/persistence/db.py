"""SQLite 存储结构：结构化表 + 每智能体记忆 JSON。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tiles_dynamic (
    idx        INTEGER PRIMARY KEY,
    explored   INTEGER NOT NULL DEFAULT 0,
    amount     INTEGER NOT NULL DEFAULT 0,
    settlement INTEGER,
    disaster   TEXT,
    ruins      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS civ (
    key  TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chronicle (
    tick INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    x    INTEGER,
    y    INTEGER,
    data TEXT
);
CREATE TABLE IF NOT EXISTS save_slots (
    name       TEXT PRIMARY KEY,   -- 存档名（槽位）
    updated_at TEXT NOT NULL,      -- 最近保存时间
    summary    TEXT NOT NULL,      -- JSON 摘要：时代/日期/人口，供选单展示
    data       TEXT NOT NULL       -- 完整存档 JSON
);
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # 旧档迁移：v1 存档的 tiles_dynamic 没有 ruins 列
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tiles_dynamic)")}
    if "ruins" not in cols:
        conn.execute("ALTER TABLE tiles_dynamic ADD COLUMN ruins INTEGER NOT NULL DEFAULT 0")
    # 旧档迁移：早期 chronicle 没有 data 列
    chron_cols = {r[1] for r in conn.execute("PRAGMA table_info(chronicle)")}
    if "data" not in chron_cols:
        conn.execute("ALTER TABLE chronicle ADD COLUMN data TEXT")
    conn.commit()
    return conn
