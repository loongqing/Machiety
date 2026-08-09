"""指令解析：shlex 分词，支持引号参数。"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

COMMAND_NAMES = [
    "watch", "miracle", "disaster", "inspire", "gift", "decree", "fund",
    "launch", "honor", "skip", "map", "epoch", "policy", "spirit",
    "wonders", "tech", "status", "history", "avatar", "prayers", "talk",
    "save", "load", "saves", "delete", "quit", "exit", "help",
]


@dataclass
class Command:
    name: str
    args: list[str] = field(default_factory=list)
    raw: str = ""


def parse_command(text: str) -> Command | None:
    text = text.strip()
    if not text:
        return None
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if not tokens:
        return None
    return Command(name=tokens[0].lower(), args=tokens[1:], raw=text)


HELP_TEXT = """可用指令（玩家扮演超越存在，干预间接且不可撤销）：
  watch [角色名/定居点名]     开启详细追踪面板（watch 无参数取消）
  miracle "神谕内容"          向全国广播一条神谕
  disaster <类型> <地点>      降下灾难：flood洪水 plague瘟疫 locust蝗灾 drought干旱
                              地点为定居点名或 x,y 坐标
  inspire idea "概念"         向文明植入技术/文化灵感
  inspire <角色名> "记忆"     直接植入一条核心记忆
  gift <角色名> <物品>        凭空赐予物品（food/iron/luxury/任意词）
  decree "政策内容"           强行颁布一项国家政策（含"宣战"可讨伐城邦）
  fund <定居点> [区域类型]    注入神力加速建设
  launch wonder "名称"        发起奇观工程
  honor <角色名>              授予国家荣誉，助其成为伟人
  avatar <角色名>             指定一位先知，神谕将借其口传播
  prayers                     查看等待你回应的祈愿
  talk <角色名> "话语"        与一位国民直接对话
  history [条数]              翻阅编年史（默认最近20条）
  skip [天数]                 快进时间（默认1天）
  map / status / epoch / policy / spirit / wonders / tech
                              查看地图说明 / 国家概况 / 时代 / 政策 / 精神 / 奇观 / 科技
  save [名称]                 存档（缺省覆盖当前存档槽位）
  load [名称]                 读档（缺省 autosave）
  saves                       列出全部存档槽位
  delete <存档名>             删除一个存档槽位
  quit / exit                 自动存档并退出游戏
  help                        显示本帮助"""
