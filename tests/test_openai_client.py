"""OpenAI 兼容客户端：正常解析、重试降级、非 JSON 降级、tier 模型选择。"""

import asyncio
import json

from aioresponses import aioresponses

from machiety.config import LLMConfig
from machiety.llm.mock import MockLLM
from machiety.llm.openai_client import OpenAIChat

URL = "http://llm.test/v1/chat/completions"


def make_cfg() -> LLMConfig:
    return LLMConfig(base_url="http://llm.test/v1", api_key="sk-test",
                     model="big-model", model_small="small-model")


def make_client() -> OpenAIChat:
    return OpenAIChat(make_cfg(), fallback=MockLLM(seed=1))


def chat_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _patch_sleep(monkeypatch):
    async def no_sleep(_):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)


def test_200_parses_json(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    with aioresponses() as m:
        m.post(URL, status=200, payload=chat_body('{"action": "gather", "reason": "x"}'))
        result = asyncio.run(client.generate("plan", {"tier": "small"}))
    assert result == {"action": "gather", "reason": "x"}
    assert client.calls == 1
    assert client.fallbacks == 0


def post_calls(m) -> list:
    key = next(k for k in m.requests if k[0] == "POST")
    return m.requests[key]


def test_500_retries_then_fallback(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    with aioresponses() as m:
        m.post(URL, status=500, repeat=True)
        result = asyncio.run(client.generate("plan", {"tier": "small"}))
    assert client.fallbacks == 1
    assert len(post_calls(m)) == 3                  # 三次重试后降级
    assert isinstance(result, dict) and result     # MockLLM 兜底仍返回可用结果


def test_non_json_falls_back(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    with aioresponses() as m:
        m.post(URL, status=200, payload=chat_body("这根本不是 JSON"), repeat=True)
        result = asyncio.run(client.generate("plan", {"tier": "small"}))
    assert client.fallbacks == 1
    assert isinstance(result, dict) and result


def test_on_error_called_on_fallback(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    errors: list[str] = []
    client.on_error = errors.append
    with aioresponses() as m:
        m.post(URL, status=500, repeat=True)
        result = asyncio.run(client.generate("plan", {"tier": "small"}))
    assert client.fallbacks == 1
    assert errors, "LLM 出错时应触发 on_error 回调"
    assert "降级" in errors[0] and "500" in errors[0]


def test_no_error_callback_when_success(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    errors: list[str] = []
    client.on_error = errors.append
    with aioresponses() as m:
        m.post(URL, status=200, payload=chat_body('{"ok": true}'))
        asyncio.run(client.generate("plan", {"tier": "small"}))
    assert errors == []


def test_game_wires_llm_error_to_bus(tmp_path):
    """Game 应将 LLM 错误回调接到事件总线，玩家能在事件框中看到提醒。"""
    from machiety.config import GameConfig
    from machiety.engine.scheduler import Game

    config = GameConfig(seed=42, width=32, height=24, settlers=12,
                        save_dir=str(tmp_path))
    llm = make_client()
    game = Game(config, llm, seed=42)
    assert llm.on_error is not None
    llm.on_error("测试错误：LLM 请求失败")
    events = [e for e in game.bus.log if e.kind == "system"]
    assert events and "测试错误" in events[-1].text


def test_tier_selects_model(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    with aioresponses() as m:
        m.post(URL, status=200, payload=chat_body('{"ok": true}'), repeat=True)

        async def both():
            await client.generate("plan", {"tier": "small"})
            await client.generate("adjudicate", {"tier": "large"})

        asyncio.run(both())

    def body_model(call):
        kwargs = getattr(call, "kwargs", None) or call[1]
        body = kwargs.get("json")
        if body is None:
            body = json.loads(kwargs.get("data"))
        return body["model"]

    calls = post_calls(m)
    assert body_model(calls[0]) == "small-model"
    assert body_model(calls[1]) == "big-model"


def body_of(call) -> dict:
    kwargs = getattr(call, "kwargs", None) or call[1]
    body = kwargs.get("json")
    if body is None:
        body = json.loads(kwargs.get("data"))
    return body


def test_default_disables_thinking(monkeypatch):
    _patch_sleep(monkeypatch)
    client = make_client()
    with aioresponses() as m:
        m.post(URL, status=200, payload=chat_body('{"ok": true}'))
        asyncio.run(client.generate("plan", {"tier": "small"}))
    body = body_of(post_calls(m)[0])
    assert body["enable_thinking"] is False
    assert "stream" not in body


SSE_BODY = (
    'data: {"choices": [{"delta": {"reasoning_content": "思考中……"}}]}\n\n'
    'data: {"choices": [{"delta": {"content": "{\\"action\\": \\"rest\\"}"}}]}\n\n'
    "data: [DONE]\n\n"
)


def test_thinking_streams_and_parses(monkeypatch):
    _patch_sleep(monkeypatch)
    cfg = make_cfg()
    cfg.thinking = True
    client = OpenAIChat(cfg, fallback=MockLLM(seed=1))
    with aioresponses() as m:
        m.post(URL, status=200, body=SSE_BODY)
        result = asyncio.run(client.generate("plan", {"tier": "small"}))
    assert result == {"action": "rest"}          # 只取 content，忽略 reasoning_content
    assert client.fallbacks == 0
    body = body_of(post_calls(m)[0])
    assert body["enable_thinking"] is True
    assert body["stream"] is True
