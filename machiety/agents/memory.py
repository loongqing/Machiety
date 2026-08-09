"""记忆流：感知记忆 → 摘要记忆 → 核心记忆，嵌入检索。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..embed.store import embed, cosine

OBSERVATION = "observation"
SUMMARY = "summary"
CORE = "core"

OBS_LIMIT = 50            # 感知记忆容量
CORE_THRESHOLD = 7.0      # 重要性 >= 该值晋升核心记忆

_next_memory_id = 1


def _new_memory_id() -> int:
    global _next_memory_id
    i = _next_memory_id
    _next_memory_id += 1
    return i


def _reserve_memory_id(up_to: int) -> None:
    """读档后推进全局 ID，避免新记忆与已恢复记忆撞号。"""
    global _next_memory_id
    if up_to >= _next_memory_id:
        _next_memory_id = up_to + 1


@dataclass
class MemoryRecord:
    id: int
    tick: int
    text: str
    importance: float
    kind: str
    embedding: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "tick": self.tick, "text": self.text,
                "importance": self.importance, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryRecord":
        rec = cls(id=int(data["id"]), tick=int(data["tick"]), text=data["text"],
                  importance=float(data["importance"]), kind=data["kind"])
        rec.embedding = embed(rec.text)
        return rec


class MemoryStream:
    def __init__(self) -> None:
        self.observations: list[MemoryRecord] = []
        self.summaries: list[MemoryRecord] = []
        self.core: list[MemoryRecord] = []

    # ---------------- 写入

    def add(self, text: str, tick: int, importance: float = 4.0) -> MemoryRecord:
        kind = CORE if importance >= CORE_THRESHOLD else OBSERVATION
        rec = MemoryRecord(id=_new_memory_id(), tick=tick, text=text,
                           importance=importance, kind=kind, embedding=embed(text))
        if kind == CORE:
            self.core.append(rec)
        else:
            self.observations.append(rec)
            if len(self.observations) > OBS_LIMIT:
                self.observations = self.observations[-OBS_LIMIT:]
        return rec

    def add_summary(self, text: str, tick: int, importance: float = 5.5) -> MemoryRecord:
        rec = MemoryRecord(id=_new_memory_id(), tick=tick, text=text,
                           importance=importance, kind=SUMMARY, embedding=embed(text))
        self.summaries.append(rec)
        if len(self.summaries) > 60:
            self.summaries = self.summaries[-60:]
        return rec

    # ---------------- 检索

    def _all(self) -> list[MemoryRecord]:
        return self.observations + self.summaries + self.core

    def retrieve(self, query: str, tick: int, k: int = 5) -> list[MemoryRecord]:
        """得分 = 相似度 * 时近衰减 * 重要性权重。"""
        qv = embed(query)
        scored = []
        for rec in self._all():
            sim = max(0.0, cosine(qv, rec.embedding))
            age_hours = max(0, tick - rec.tick)
            recency = 0.3 + 0.7 / (1.0 + age_hours / 96.0)
            score = (0.5 * sim + 0.3 * recency) * (0.5 + rec.importance / 10.0)
            scored.append((score, rec))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [rec for _, rec in scored[:k]]

    def recent(self, n: int = 8) -> list[MemoryRecord]:
        return self.observations[-n:]

    def day_events(self, day_start_tick: int) -> list[str]:
        return [r.text for r in self.observations if r.tick >= day_start_tick]

    # ---------------- 序列化

    def to_dict(self) -> dict:
        return {
            "observations": [r.to_dict() for r in self.observations],
            "summaries": [r.to_dict() for r in self.summaries],
            "core": [r.to_dict() for r in self.core],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryStream":
        stream = cls()
        stream.observations = [MemoryRecord.from_dict(d) for d in data.get("observations", [])]
        stream.summaries = [MemoryRecord.from_dict(d) for d in data.get("summaries", [])]
        stream.core = [MemoryRecord.from_dict(d) for d in data.get("core", [])]
        restored = stream.observations + stream.summaries + stream.core
        if restored:
            _reserve_memory_id(max(r.id for r in restored))
        return stream
