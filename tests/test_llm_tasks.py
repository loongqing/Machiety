"""新 LLM 任务：MockLLM 离线返回结构完整。"""

import asyncio

from machiety.llm.mock import MockLLM


def test_interpret_returns_reactions():
    llm = MockLLM(seed=1)
    result = asyncio.run(llm.generate("interpret", {
        "event": {"kind": "miracle", "text": "雨水将赐福此地"},
        "reps": [{"name": "卡恩", "profession": "农民", "personality": "温和"}],
        "tier": "large"}))
    assert isinstance(result.get("reactions"), list) and result["reactions"]
    r = result["reactions"][0]
    assert r["name"] == "卡恩" and r["spread_line"]
    assert r["sentiment"] in (-1, 0, 1)


def test_prayer_returns_valid_intent():
    llm = MockLLM(seed=1)
    result = asyncio.run(llm.generate("prayer", {
        "candidates": [{"name": "卡恩", "profession": "农民", "need": "生存",
                        "settlement": "晨曦城", "mood": "忧虑"}], "tier": "small"}))
    assert result["prayers"]
    p = result["prayers"][0]
    assert p["intent"] in {"miracle", "gift", "disaster", "decree", "fund", "inspire"}
    assert p["text"]


def test_debate_swing_in_range():
    llm = MockLLM(seed=1)
    result = asyncio.run(llm.generate("debate", {
        "policy": {"name": "自由市集", "slot": "economy", "description": "开放集市",
                   "proposer": "商人行会"}, "opponent": "学者会", "tier": "large"}))
    assert -10 <= int(result["swing"]) <= 10
    assert result["for"] and result["against"]


def test_council_focus_whitelist():
    llm = MockLLM(seed=1)
    result = asyncio.run(llm.generate("council", {
        "settlement": "晨曦城", "disaster": "洪水", "leader": "卡恩",
        "food_stock": 5.0, "population": 4, "suggested_focus": "build", "tier": "large"}))
    assert result["focus"] in {"food", "build", "spirit", "safety"}
    assert result["strategy"]


def test_commune_reply():
    llm = MockLLM(seed=1)
    result = asyncio.run(llm.generate("commune", {
        "words": "你所求为何", "agent": {"name": "卡恩", "profession": "农民"},
        "memories": [], "tier": "small"}))
    assert result["reply"] and result["reaction"]
