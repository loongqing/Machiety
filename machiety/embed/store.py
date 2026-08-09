"""轻量哈希嵌入向量库：离线可用、可复现，接口兼容后续替换为 API embeddings。"""

from __future__ import annotations

import math
import re
import zlib

DIM = 96
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


def embed(text: str) -> list[float]:
    """将文本映射为固定维度的归一化向量（分词哈希叠加）。"""
    vec = [0.0] * DIM
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vec
    for tok in tokens:
        h = zlib.crc32(tok.encode("utf-8"))
        idx = h % DIM
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    """两个已归一化向量的余弦相似度（约 -1~1，映射到 0~1 使用）。"""
    return sum(x * y for x, y in zip(a, b))
