"""LLM 抽象接口：所有模拟决策经由此层，输出统一为 JSON dict。

task 取值约定：
  plan             单角色小时计划（small）
  talk             同地点批量对话（small）
  adjudicate       冲突裁决（large）
  reflect          夜间反思与记忆压缩（small）
  epiphany         技术/文化顿悟（large）
  policy_proposal  派系法案提案（large）
  era_event        时代更迭叙事（large）
  wonder_effect    奇观完工效果（large）
  great_person     伟人天赋（large）
  wonder_launch    远见者倡议奇观（large）
  interpret        干预事件代表解读（large/small）
  prayer           国民祈愿（small）
  debate           议会辩论（large）
  council          灾难应对会议（large）
  commune          玩家与角色对话（small）
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Callable


def parse_json_loose(text: str) -> dict | None:
    """宽容解析 LLM 返回的 JSON：剥离代码围栏、截取首个花括号块。"""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


class BaseLLM:
    """所有 LLM 后端的抽象基类。"""

    name = "base"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.calls = 0          # 统计调用次数（headless 报告用）
        self.fallbacks = 0      # 降级次数
        self.on_error: Callable[[str], None] | None = None  # LLM 出错回调（UI 事件提醒用）

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        """按任务类型生成结构化结果；永不抛异常，失败应返回合理默认。"""
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover
        pass
