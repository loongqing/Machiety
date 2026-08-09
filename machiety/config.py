"""配置加载：读取 config.toml（OpenAI 兼容 LLM 配置与世界参数）。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    model_small: str = ""
    concurrency: int = 8
    timeout: float = 60.0
    temperature: float = 0.8
    max_tokens: int = 600
    economy: bool = False       # 节流模式：规划缓存 + 分组反思，降低 LLM 调用量
    thinking: bool = False      # 思考模式：请求附带 enable_thinking，启用 LLM 深度思考

    @property
    def available(self) -> bool:
        """是否具备调用真实 LLM 的最低条件。"""
        return bool(self.base_url and self.api_key and self.model)


@dataclass
class GameConfig:
    seed: int | None = None
    width: int = 64
    height: int = 40
    settlers: int = 50
    save_dir: str = "saves"
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_config(path: str | Path = "config.toml") -> GameConfig:
    """加载配置；文件不存在时返回全默认值（离线 Mock 模式）。"""
    cfg = GameConfig()
    p = Path(path)
    if not p.exists():
        return cfg
    with open(p, "rb") as f:
        raw = tomllib.load(f)

    world = raw.get("world", {})
    cfg.width = int(world.get("width", cfg.width))
    cfg.height = int(world.get("height", cfg.height))
    cfg.settlers = int(world.get("settlers", cfg.settlers))
    cfg.seed = world.get("seed", None)
    if cfg.seed is not None:
        cfg.seed = int(cfg.seed)

    llm = raw.get("llm", {})
    cfg.llm = LLMConfig(
        base_url=str(llm.get("base_url", "")).rstrip("/"),
        api_key=str(llm.get("api_key", "")),
        model=str(llm.get("model", "")),
        model_small=str(llm.get("model_small", "")) or str(llm.get("model", "")),
        concurrency=int(llm.get("concurrency", 8)),
        timeout=float(llm.get("timeout", 60.0)),
        temperature=float(llm.get("temperature", 0.8)),
        max_tokens=int(llm.get("max_tokens", 600)),
        economy=bool(llm.get("economy", False)),
        thinking=bool(llm.get("thinking", False)),
    )
    if cfg.llm.api_key in ("sk-xxxx", ""):
        # 示例占位符视为未配置
        cfg.llm.api_key = "" if cfg.llm.api_key == "sk-xxxx" else cfg.llm.api_key
    return cfg
