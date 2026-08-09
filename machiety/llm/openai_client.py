"""OpenAI 兼容 API 客户端：异步并发调用，失败自动降级到兜底 LLM。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from ..config import LLMConfig
from .base import BaseLLM, parse_json_loose
from .prompts import build_messages


class OpenAIChat(BaseLLM):
    name = "openai"

    def __init__(self, cfg: LLMConfig, fallback: BaseLLM, seed: int = 0) -> None:
        super().__init__(seed)
        self.cfg = cfg
        self.fallback = fallback
        self.sem = asyncio.Semaphore(max(1, cfg.concurrency))
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.cfg.timeout)
            )
        return self._session

    def _model_for(self, tier: str) -> str:
        return self.cfg.model_small if tier == "small" and self.cfg.model_small else self.cfg.model

    async def _read_stream(self, resp: aiohttp.ClientResponse) -> str:
        """累积 SSE 流式输出的 content（忽略 reasoning_content 思考过程）。"""
        parts: list[str] = []
        async for raw in resp.content:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                # 严格解析：SSE 块的 content 常含转义引号，宽松解析会误判花括号深度
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            choices = obj.get("choices") or []
            if choices:
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    parts.append(piece)
        return "".join(parts)

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        tier = payload.get("tier", "small")
        body = {
            "model": self._model_for(tier),
            "messages": build_messages(task, payload),
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "enable_thinking": self.cfg.thinking,
        }
        if self.cfg.thinking:
            # 部分思考模型（如 Qwen3）要求思考模式下必须流式输出
            body["stream"] = True
        headers = {"Authorization": f"Bearer {self.cfg.api_key}",
                   "Content-Type": "application/json"}
        url = f"{self.cfg.base_url}/chat/completions"

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                async with self.sem:
                    session = await self._ensure_session()
                    async with session.post(url, json=body, headers=headers) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"HTTP {resp.status}: {await resp.text()}")
                        if body.get("stream"):
                            content = await self._read_stream(resp)
                        else:
                            data = await resp.json()
                            content = data["choices"][0]["message"]["content"]
                parsed = parse_json_loose(content)
                if parsed is None:
                    raise ValueError(f"LLM 返回无法解析为 JSON: {content[:120]}")
                return parsed
            except Exception as e:  # noqa: BLE001 - 任何异常都走降级链路
                last_err = e
                await asyncio.sleep(0.5 * (2 ** attempt))

        # 全部重试失败：降级兜底，绝不打断模拟
        self.fallbacks += 1
        if self.on_error:
            try:
                self.on_error(f"LLM 请求失败，已降级到离线兜底：{last_err}")
            except Exception:  # noqa: BLE001 - 回调失败不影响模拟
                pass
        return await self.fallback.generate(task, payload)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
