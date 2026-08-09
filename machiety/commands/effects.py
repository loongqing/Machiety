"""指令效果落地：每条神谕、灾难与恩典如何改变世界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..civilization.city import DISTRICT_TYPES

if TYPE_CHECKING:
    from ..engine.scheduler import Game

from .parser import Command, HELP_TEXT

DISASTER_TYPES = {"flood", "plague", "locust", "drought"}

# inspire idea 可指定的领域别名 → 灵感池类别
DOMAIN_ALIASES = {
    "food": "food", "粮食": "food", "农业": "food", "食物": "food",
    "war": "war", "战争": "war", "军事": "war", "战斗": "war",
    "spirit": "spirit", "精神": "spirit", "信仰": "spirit", "文化": "spirit",
    "economy": "economy", "经济": "economy", "贸易": "economy", "商业": "economy",
    "build": "build", "建造": "build", "建筑": "build", "工程": "build",
}

MAP_LEGEND = """地图图例：
  地形  ~ 海洋   . 平原   ^ 丘陵   # 森林   A 山脉   = 河流
  资源  f 鱼群   t 木材   w 谷物   h 马匹   i 铁矿   $ 奢侈品
  人文  @ 国民（多人显示数量）  定居点以 [名称] 标注于侧栏
  迷雾  ░ 未探索（探索后地形永久可见）
操作：方向键移动光标  Enter 查看详情  w 追踪光标处角色  m 切换视图  z 缩放
      空格 暂停  鼠标点击定位（终端支持时）"""


@dataclass
class CommandResult:
    text: str
    new_game: "Game | None" = None     # load 指令返回新世界
    quit_app: bool = False             # quit/exit 指令请求退出应用


def _resolve_location(game: "Game", text: str) -> tuple[int, int] | None:
    if "," in text:
        try:
            x, y = (int(v) for v in text.split(",", 1))
            if game.world.in_bounds(x, y):
                return x, y
        except ValueError:
            pass
        return None
    s = game.cities.by_name(text)
    return (s.x, s.y) if s else None


async def execute_command(game: "Game", cmd: Command) -> CommandResult:
    name, args = cmd.name, cmd.args

    if name == "help":
        return CommandResult(HELP_TEXT)

    if name == "map":
        return CommandResult(MAP_LEGEND)

    if name == "status":
        st = game.stats()
        return CommandResult(
            f"{game.clock.date_str}\n"
            f"人口：{st['population']}  定居点：{st['settlements']}  公共存粮：{st['food_stock']}\n"
            f"总财富：{st['wealth']}  已发明技术：{st['techs']}  时代：{st['era']}\n"
            f"国家精神：{game.policy.spirit()}\n"
            f"已探索：{game.world.explored_ratio():.0%}  LLM后端：{game.llm.name}")

    if name == "epoch":
        return CommandResult(game.epoch.describe(game))

    if name == "policy":
        return CommandResult(game.policy.describe(game))

    if name == "spirit":
        return CommandResult(f"国家精神：{game.policy.spirit()}")

    if name == "wonders":
        return CommandResult(game.wonders.describe())

    if name == "tech":
        if not game.tech.techs:
            pool = "、".join(f"{k}:{v:.0f}" for k, v in game.tech.pool.items() if v > 0)
            return CommandResult(f"尚无发明。灵感池：{pool or '空'}")
        lines = [f"「{t.name}」（{t.category}） 发明者{t.inventor} 第{t.day}日 传播{t.spread:.0%}\n    {t.effect}"
                 for t in game.tech.techs]
        return CommandResult("\n".join(lines))

    if name == "history":
        n = 20
        if args:
            try:
                n = max(1, min(100, int(args[0])))
            except ValueError:
                return CommandResult("用法：history [条数]")
        entries = game.bus.chronicle[-n:]
        if not entries:
            return CommandResult("编年史尚是空白，历史正等待书写")
        lines = [f"第{e.tick // 24 + 1}日 [{e.kind}] {e.text}" for e in entries]
        return CommandResult(f"—— Machiety 编年史（最近 {len(entries)} 条）——\n" + "\n".join(lines))

    if name == "watch":
        if not args:
            game.watched = None
            return CommandResult("已取消追踪")
        target = " ".join(args)
        if game.manager.by_name(target) or game.cities.by_name(target):
            game.watched = target
            return CommandResult(f"开始追踪「{target}」，详见侧栏")
        return CommandResult(f"找不到名为「{target}」的角色或定居点")

    if name == "prayers":
        return CommandResult(game.prayers.describe())

    if name == "talk":
        if len(args) < 2:
            return CommandResult("用法：talk <角色名> \"话语\"")
        agent = game.manager.by_name(args[0])
        if agent is None:
            return CommandResult(f"找不到角色：{args[0]}")
        words = " ".join(args[1:]).strip()
        if not words:
            return CommandResult("请对他说些什么，例如 talk 卡恩 \"你所求为何\"")
        tick = game.clock.total_hours
        memories = [m.text for m in agent.memory.retrieve(words, tick, k=3)]
        result = await game.llm.generate("commune", {
            "words": words,
            "agent": {"name": agent.name, "profession": agent.profession_name,
                      "personality": agent.personality.describe(),
                      "mood": agent.mood, "prophet": agent.prophet,
                      "needs": {k: round(v, 2) for k, v in agent.needs.items()}},
            "memories": memories,
            "tier": "small",
        })
        reply = result.get("reply") or f"{agent.name} 俯首领命：凡人在听，请神示下"
        reaction = result.get("reaction") or "心怀敬畏"
        agent.remember(f"神明亲自对我说话：「{words}」。我{reaction}", tick, importance=7.0)
        agent.needs["social"] = min(1.0, agent.needs["social"] + 0.1)
        agent.clamp_needs()
        game.bus.publish("commune", f"神与 {agent.name} 低语交谈",
                         tick=tick, x=agent.x, y=agent.y)
        return CommandResult(f"{agent.name}：「{reply}」")

    if name == "miracle":
        text = " ".join(args).strip()
        if not text:
            return CommandResult("神谕需要内容，例如 miracle \"雨水将赐福此地\"")
        tick = game.clock.total_hours
        for agent in game.manager.alive():
            agent.remember(f"神谕响彻天际：「{text}」", tick, importance=6.0)
            agent.needs["self_actualization"] = min(1.0, agent.needs["self_actualization"] + 0.05)
        # 先知化身：独享神谕原文，并肩负传播之责
        for prophet in (a for a in game.manager.alive() if a.prophet):
            prophet.remember(f"我作为先知，亲耳聆听了这道神谕的原文：「{text}」",
                             tick, importance=9.0)
            if "传播神谕" not in prophet.goals:
                prophet.goals.append("传播神谕")
                if len(prophet.goals) > 3:
                    prophet.goals.pop(0)
        game.epoch.cultural_events += 1
        game.bus.publish("miracle", f"神谕降临：「{text}」", tick=tick, x=game.spawn_x, y=game.spawn_y)
        await game.reaction.on_intervention(game, "miracle", text, game.spawn_x, game.spawn_y)
        granted = game.prayers.try_grant(game, name, " ".join(args))
        # 干预哲学：神谕可能被曲解
        if game.rng.random() < 0.25:
            confused = game.rng.choice(game.manager.alive())
            confused.remember(f"我怀疑所谓神谕「{text}」只是集体的幻觉", tick, importance=5.0)
            return CommandResult(f"神谕已广播全国……但 {confused.name} 似乎将其解读为集体幻觉" + granted)
        return CommandResult("神谕已响彻全国，万民屏息聆听" + granted)

    if name == "disaster":
        if len(args) < 2:
            return CommandResult("用法：disaster <flood|plague|locust|drought> <定居点名或x,y>")
        dtype = args[0].lower()
        if dtype not in DISASTER_TYPES:
            return CommandResult(f"未知灾难类型：{dtype}（可选 flood/plague/locust/drought）")
        pos = _resolve_location(game, args[1])
        if pos is None:
            return CommandResult(f"找不到地点：{args[1]}")
        msg = game.unleash_disaster(dtype, *pos)
        await game.reaction.on_intervention(
            game, "disaster", f"{dtype} 之灾降临于 {args[1]}", pos[0], pos[1])
        return CommandResult(msg + game.prayers.try_grant(game, name, " ".join(args)))

    if name == "inspire":
        if not args:
            return CommandResult("用法：inspire idea \"概念\" 或 inspire <角色名> \"记忆\"")
        if args[0].lower() == "idea":
            # 可选指定领域：inspire idea <领域> "概念"；未指定则随机领域
            cat = None
            rest = args[1:]
            if rest and rest[0] in DOMAIN_ALIASES:
                cat = DOMAIN_ALIASES[rest[0]]
                rest = rest[1:]
            concept = " ".join(rest).strip()
            if not concept:
                return CommandResult("请给出灵感概念，例如 inspire idea 粮食 灌溉")
            cat = cat or game.rng.choice(list(game.tech.pool.keys()))
            game.tech.add_inspiration(cat, 6.0)
            game.tech.pending_seed = concept
            game.bus.publish("inspire", f"一缕灵感拂过文明：「{concept}」", tick=game.clock.total_hours)
            await game.reaction.on_intervention(
                game, "inspire", concept, game.spawn_x, game.spawn_y)
            return CommandResult(f"你将「{concept}」植入文明的梦境（{cat} 领域），智者或将因此顿悟"
                                 + game.prayers.try_grant(game, name, " ".join(args)))
        agent = game.manager.by_name(args[0])
        if agent is None:
            return CommandResult(f"找不到角色：{args[0]}")
        memory_text = " ".join(args[1:]).strip()
        if not memory_text:
            return CommandResult("请给出要植入的记忆内容")
        agent.remember(f"（深植的记忆）{memory_text}", game.clock.total_hours, importance=9.0)
        await game.reaction.on_intervention(
            game, "inspire", memory_text, agent.x, agent.y)
        return CommandResult(f"一段不属于尘世的记忆植入了 {agent.name} 的脑海"
                             + game.prayers.try_grant(game, name, " ".join(args)))

    if name == "gift":
        if len(args) < 2:
            return CommandResult("用法：gift <角色名> <物品>")
        agent = game.manager.by_name(args[0])
        if agent is None:
            return CommandResult(f"找不到角色：{args[0]}")
        item = args[1]
        if item == "food":
            agent.inventory["food"] = agent.inventory.get("food", 0) + 10
        elif item in ("gold", "wealth"):
            agent.wealth += 20
        else:
            agent.inventory[item] = agent.inventory.get(item, 0) + 1
            agent.wealth += 5
        agent.remember(f"天降神赐，我得到了 {item}，此事必有深意",
                       game.clock.total_hours, importance=7.5)
        agent.influence += 1.0
        game.bus.publish("gift", f"神赐 {item} 降临于 {agent.name}",
                         tick=game.clock.total_hours, x=agent.x, y=agent.y)
        await game.reaction.on_intervention(
            game, "gift", f"{item} 被赐予 {agent.name}", agent.x, agent.y)
        return CommandResult(f"{item} 已赐予 {agent.name}，众人投来敬畏的目光"
                             + game.prayers.try_grant(game, name, " ".join(args)))

    if name == "decree":
        text = " ".join(args).strip()
        if not text:
            return CommandResult("用法：decree \"政策内容\"")
        msg = game.policy.decree(game, text)
        game.bus.publish("policy", f"神谕颁布政策：{text}", tick=game.clock.total_hours)
        await game.reaction.on_intervention(game, "decree", text, game.spawn_x, game.spawn_y)
        return CommandResult(msg + game.prayers.try_grant(game, name, " ".join(args)))

    if name == "fund":
        if not args:
            return CommandResult("用法：fund <定居点> [区域类型]")
        s = game.cities.by_name(args[0])
        if s is None:
            names = "、".join(x.name for x in game.cities.settlements) or "尚无定居点"
            return CommandResult(f"找不到定居点「{args[0]}」。现有：{names}")
        dtype = args[1] if len(args) > 1 else None
        if dtype and dtype not in DISTRICT_TYPES:
            return CommandResult(f"未知区域类型：{dtype}（可选 {'/'.join(DISTRICT_TYPES)}）")
        msg = game.cities.fund(game, s, dtype)
        game.bus.publish("city", f"神力注入「{s.name}」", tick=game.clock.total_hours, x=s.x, y=s.y)
        return CommandResult(msg + game.prayers.try_grant(game, name, " ".join(args)))

    if name == "launch":
        if not args or args[0].lower() != "wonder":
            return CommandResult("用法：launch wonder \"名称\"")
        wonder_name = " ".join(args[1:]).strip()
        if not wonder_name:
            return CommandResult("请为奇观命名")
        msg = game.wonders.launch(game, wonder_name)
        return CommandResult(msg)

    if name == "avatar":
        if not args:
            return CommandResult("用法：avatar <角色名>")
        agent = game.manager.by_name(args[0])
        if agent is None:
            return CommandResult(f"找不到角色：{args[0]}")
        for a in game.manager.alive():
            a.prophet = False
        agent.prophet = True
        agent.influence += 5.0
        agent.remember("（深植的记忆）我听到了神的声音，自此以先知之身行走人间",
                       game.clock.total_hours, importance=9.5)
        game.bus.publish("miracle", f"{agent.name} 被选为先知，成为神在人间的化身",
                         tick=game.clock.total_hours, x=agent.x, y=agent.y)
        await game.reaction.on_intervention(
            game, "avatar", f"{agent.name} 被立为先知", agent.x, agent.y)
        return CommandResult(f"{agent.name} 已被立为先知（影响力 +5），神谕将经由其口传达")

    if name == "honor":
        if not args:
            return CommandResult("用法：honor <角色名>")
        agent = game.manager.by_name(args[0])
        if agent is None:
            return CommandResult(f"找不到角色：{args[0]}")
        agent.honor += 20.0
        agent.influence += 2.0
        agent.achievement += 1
        agent.remember("国家荣誉加身，万民称颂我的功绩", game.clock.total_hours, importance=8.5)
        game.bus.publish("honor", f"{agent.name} 被授予国家荣誉",
                         tick=game.clock.total_hours, x=agent.x, y=agent.y)
        await game.great.check(game, agent)
        if agent.great_title:
            return CommandResult(f"{agent.name} 沐浴荣光，晋升为「{agent.great_title}」！")
        return CommandResult(f"{agent.name} 被授予国家荣誉，声望大涨")

    if name == "skip":
        days = 1
        if args:
            try:
                days = max(1, min(30, int(args[0])))
            except ValueError:
                return CommandResult("用法：skip [天数]")
        await game.skip_days(days)
        st = game.stats()
        return CommandResult(f"时间快进 {days} 天 —— 人口{st['population']}，"
                             f"技术{st['techs']}项，时代：{st['era']}")

    if name == "save":
        from ..persistence.saver import save_game
        save_name = " ".join(args).strip() if args else (game.current_slot or "autosave")
        save_game(game, save_name)
        game.current_slot = save_name
        return CommandResult(f"已存档至「{save_name}」（存档库 saves/saves.db）")

    if name == "load":
        from ..persistence.saver import SaveVersionError, load_game, list_saves
        save_name = " ".join(args).strip() if args else "autosave"
        try:
            new_game = load_game(save_name, game.config, game.llm)
        except FileNotFoundError:
            return CommandResult(f"找不到存档「{save_name}」。现有存档：{'、'.join(list_saves(game.config)) or '无'}")
        except SaveVersionError as e:
            return CommandResult(f"存档无法载入：{e}")
        return CommandResult(f"已读取存档「{save_name}」，时间回到 {new_game.clock.date_str}",
                             new_game=new_game)

    if name == "saves":
        from ..persistence.saver import list_slots
        slots = list_slots(game.config)
        if not slots:
            return CommandResult("尚无存档。使用 save [名称] 铭刻当前历史")
        lines = []
        for i, s in enumerate(slots, 1):
            info = s["info"]
            mark = "（当前）" if s["name"] == game.current_slot else ""
            lines.append(f" {i}. 「{s['name']}」{mark} {info.get('progress', '')} · "
                         f"{info.get('era', '')}时代 · 人口{info.get('population', '?')}"
                         f"  更新于 {s['updated_at']}")
        return CommandResult("存档列表：\n" + "\n".join(lines))

    if name == "delete":
        if not args:
            return CommandResult("用法：delete <存档名>（saves 查看列表）")
        from ..persistence.saver import delete_save
        target = " ".join(args).strip()
        if delete_save(game.config, target):
            if game.current_slot == target:
                game.current_slot = None
            return CommandResult(f"存档「{target}」已删除")
        return CommandResult(f"找不到存档「{target}」（saves 查看列表）")

    if name in ("quit", "exit"):
        # 实际保存与退出由应用层执行（见 MachietyApp.on_input_submitted）
        return CommandResult("正在自动存档，愿文明之火永续。别了，超越存在", quit_app=True)

    return CommandResult(f"未知指令：{name}（输入 help 查看全部指令）")
