"""提示词模板：将结构化 payload 组装为 OpenAI 兼容的 messages。"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_BASE = (
    "你是 Machiety 国家模拟游戏的生成引擎。你收到的是一段模拟场景的 JSON 描述，"
    "必须以单个 JSON 对象作答，不得输出任何解释文字、代码围栏或多余内容。"
)

TASK_SCHEMA: dict[str, str] = {
    "plan": (
        "为该角色生成接下来一小时的具体行动计划。"
        '输出 {"action": "gather|move|talk|build|rest|worship|research|trade|explore|patrol", '
        '"target": "对象或资源名(可空)", "direction": "n|s|e|w 或空", "reason": "简短中文动机"}'
    ),
    "talk": (
        "为同处一地的多名角色生成一段群像对话。"
        '输出 {"summary": "一句话场景描述", "topic": "话题", '
        '"deltas": [["甲","乙",整数好感变化(-2~2)], ...]}'
    ),
    "adjudicate": (
        "依据双方人格、地位与历史裁决这场冲突。"
        '输出 {"winner": "胜者名", "loser": "败者名", "outcome": "一句话结果", "spoils": "food|wealth|无"}'
    ),
    "reflect": (
        "为该角色做当夜反思，压缩今日记忆。"
        '输出 {"summary": "当日总结", "mood": "心境", "new_goal": "新目标或 null"}'
    ),
    "epiphany": (
        "该角色在长期困扰后迎来顿悟，发明一项新技术或文化概念。"
        '输出 {"name": "技术名", "category": "类别", "effect": "对社会的具体效果"}'
    ),
    "policy_proposal": (
        "以该派系的立场提出一项法案。"
        '输出 {"name": "法案名", "slot": "military|economy|diplomacy|culture", '
        '"effect": "food|wealth|research|culture|war|stability", "description": "条文要点"}'
    ),
    "era_event": (
        "为文明跨入新时代撰写一段史诗式叙事。"
        '输出 {"text": "不超过80字的叙事"}'
    ),
    "wonder_effect": (
        "奇观落成，为它生成永久性全局效果。"
        '输出 {"effect": "food_bonus|research_bonus|explore_bonus|trade_bonus", "text": "一句话庆典描述"}'
    ),
    "great_person": (
        "该角色因卓越成就成为伟人，生成其称号与独特天赋。"
        '输出 {"title": "称号", "gift": "天赋描述", '
        '"gift_kind": "research|food|war|culture|wealth|stability"}'
    ),
    "wonder_launch": (
        "一位远见者倡议修建一座传世奇观，为它命名。"
        '输出 {"name": "奇观名"}'
    ),
    "interpret": (
        "玩家刚刚对世界施加了一次干预，这些代表人物各自作何解读。"
        '输出 {"reactions": [{"name": "代表名", "interpretation": "个人解读", '
        '"spread_line": "向他人转述的一句话", "sentiment": -1|0|1}]}'
    ),
    "prayer": (
        "这些角色向天神（玩家）祈愿，诉求应与其困境相符。"
        '输出 {"prayers": [{"name": "祈愿者", "text": "祈愿内容", '
        '"intent": "miracle|gift|disaster|decree|fund|inspire", "target": "相关对象名或空"}]}'
    ),
    "debate": (
        "议会就法案辩论：提案方陈述支持理由，反对方驳斥。"
        '输出 {"for": "支持陈词", "against": "反对陈词", "swing": 整数(-10~10，辩论对票数的净影响)}'
    ),
    "council": (
        "灾后定居点召开应对会议，领袖提出恢复策略。"
        '输出 {"strategy": "策略要点", "focus": "food|build|spirit|safety", "text": "一句话会议纪实"}'
    ),
    "commune": (
        "天神（玩家）直接与该角色对话，以角色的身份、性格与记忆作答。"
        '输出 {"reply": "角色的回答", "reaction": "角色的内心反应"}'
    ),
}


def build_messages(task: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    schema = TASK_SCHEMA.get(task, "请以 JSON 对象作答。")
    user = schema + "\n\n场景数据：\n" + json.dumps(payload, ensure_ascii=False, default=str)
    return [
        {"role": "system", "content": SYSTEM_BASE},
        {"role": "user", "content": user},
    ]
