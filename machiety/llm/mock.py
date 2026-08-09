"""MockLLM：离线模板驱动后端，保证无 API Key 时游戏全程可玩且可复现。"""

from __future__ import annotations

from typing import Any

from .base import BaseLLM

TECH_IDEAS = {
    "food": [
        ("灌溉技术", "开挖水渠引河灌溉，农田产出大幅提升"),
        ("作物轮作", "土地轮流休耕，谷物产量稳步上升"),
        ("畜力犁具", "以畜力翻耕土地，开垦速度倍增"),
        ("粮仓储存", "建造干燥粮仓，食物损耗显著降低"),
    ],
    "war": [
        ("青铜锻造", "铸造青铜兵器，士兵战斗力提升"),
        ("城墙工事", "夯土筑墙，定居点防御力大增"),
        ("复合弓", "弓射程更远，狩猎与作战皆受益"),
        ("方阵操典", "士兵协同操练，冲突胜率提高"),
    ],
    "spirit": [
        ("历法祭祀", "制定历法与祭典，民心趋于安定"),
        ("史诗吟游", "吟游诗人传唱史诗，文化认同增强"),
        ("冥想修行", "静修之风盛行，角色的自我实现需求更易满足"),
    ],
    "economy": [
        ("贝壳货币", "以贝壳为一般等价物，交易效率提升"),
        ("度量衡", "统一度量，商人纠纷减少"),
        ("商队驿站", "远方商路开通，奢侈品流入"),
    ],
    "build": [
        ("拱形结构", "建筑更坚固，区域造价降低"),
        ("水力磨坊", "河水驱动磨坊，粮食加工效率倍增"),
        ("制图术", "绘制地图，探索迷雾的速度加快"),
    ],
}

MOODS = ["平静", "振奋", "忧虑", "满足", "躁动", "虔诚"]

TOPICS = ["收成", "远方的传闻", "神灵的旨意", "孩子的未来", "谁该掌权", "新技术", "旧日恩怨", "集市价格"]


class MockLLM(BaseLLM):
    """按意图模板 + 种子随机返回结果。"""

    name = "mock"

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        handler = getattr(self, f"_task_{task}", None)
        if handler is None:
            return {}
        return handler(payload)

    # ---------------- 角色小时计划

    def _task_plan(self, p: dict) -> dict:
        agent = p.get("agent", {})
        place = p.get("place", {})
        needs = agent.get("needs", {})
        prof = agent.get("profession", "farmer")
        nearby = p.get("nearby", [])
        is_night = p.get("is_night", False)

        def plan(action: str, target: str = "", direction: str = "", reason: str = "") -> dict:
            return {"action": action, "target": target, "direction": direction, "reason": reason}

        if is_night:
            return plan("rest", reason="夜幕降临，需要休息")
        if needs.get("survival", 1.0) < 0.4:
            if place.get("food_resource"):
                return plan("gather", target=place.get("resource", ""), reason="饥肠辘辘，就地觅食")
            return plan("gather", reason="饥饿驱使我寻找食物")
        if needs.get("safety", 1.0) < 0.35:
            return plan("build", reason="缺乏安全感，修缮居所")
        if needs.get("social", 1.0) < 0.35 and nearby:
            return plan("talk", target=nearby[0], reason="渴望与人交流")

        by_prof = {
            "farmer": plan("gather", target="grain", reason="耕作田间"),
            "hunter": plan("gather", target="food", reason="外出狩猎"),
            "fisher": plan("gather", target="fish", reason="撒网捕鱼"),
            "artisan": plan("build", reason="打磨器物、修建房屋"),
            "merchant": plan("trade", target=(nearby[0] if nearby else ""), reason="寻找交易伙伴"),
            "soldier": plan("patrol", direction=self.rng.choice(["n", "s", "e", "w"]), reason="巡防四方"),
            "official": plan("talk", target=(nearby[0] if nearby else ""), reason="协调事务、听取民情"),
            "priest": plan("worship", reason="主持仪式、安抚人心"),
            "scholar": plan("research", reason="观察世界、思索难题"),
        }
        base = by_prof.get(prof, plan("explore", direction=self.rng.choice(["n", "s", "e", "w"]), reason="四处看看"))
        if base["action"] in ("patrol", "explore") and not base.get("direction"):
            base["direction"] = self.rng.choice(["n", "s", "e", "w"])
        if self.rng.random() < 0.15:
            return plan("explore", direction=self.rng.choice(["n", "s", "e", "w"]), reason="对未知之地心生好奇")
        return base

    # ---------------- 批量对话

    def _task_talk(self, p: dict) -> dict:
        names: list[str] = p.get("agents", [])
        topic = self.rng.choice(TOPICS)
        deltas = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                deltas.append([names[i], names[j], self.rng.choice([-1, 1, 1, 2])])
        summary = "与".join(names[:3]) + f" 围坐交谈，话题是{topic}" + ("，气氛融洽" if self.rng.random() < 0.7 else "，不欢而散")
        return {"summary": summary, "topic": topic, "deltas": deltas}

    # ---------------- 冲突裁决

    def _task_adjudicate(self, p: dict) -> dict:
        a, b = p.get("a", {}), p.get("b", {})
        score_a = a.get("influence", 1.0) + self.rng.random() * 2
        score_b = b.get("influence", 1.0) + self.rng.random() * 2
        winner, loser = (a, b) if score_a >= score_b else (b, a)
        reason = p.get("reason", "资源争夺")
        outcome = f"{winner.get('name')} 在{reason}中压过了 {loser.get('name')}，迫使对方让步"
        return {"winner": winner.get("name"), "loser": loser.get("name"),
                "outcome": outcome, "spoils": "food"}

    # ---------------- 夜间反思

    def _task_reflect(self, p: dict) -> dict:
        name = p.get("name", "某人")
        events = p.get("day_events", [])
        if events:
            summary = f"{name} 回想今日：{events[0]}" + (f"；此外还经历了 {len(events) - 1} 件事" if len(events) > 1 else "")
        else:
            summary = f"{name} 度过了平淡的一天"
        new_goal = None
        if self.rng.random() < 0.06:
            new_goal = self.rng.choice(["积累财富", "获得权力", "探索世界尽头", "成为受人敬仰的人", "寻找信仰的答案"])
        return {"summary": summary, "mood": self.rng.choice(MOODS), "new_goal": new_goal}

    # ---------------- 顿悟

    def _task_epiphany(self, p: dict) -> dict:
        cat = p.get("category", "food")
        taken = set(p.get("taken", []))
        ideas = [(n, e) for n, e in (TECH_IDEAS.get(cat) or TECH_IDEAS["food"])
                 if n not in taken]
        if not ideas:
            # 灵感枯竭：返回已发明的名字，调用方会退回灵感
            ideas = TECH_IDEAS.get(cat) or TECH_IDEAS["food"]
        name, effect = self.rng.choice(ideas)
        return {"name": name, "category": cat, "effect": effect}

    # ---------------- 政策提案

    def _task_policy_proposal(self, p: dict) -> dict:
        templates = {
            "商人行会": ("自由市集", "economy", "开放集市贸易，商人免税三日，财富流动加快", "wealth"),
            "军人集团": ("全民征召", "military", "战时所有青壮皆有守土之责，军力增强", "war"),
            "祭司团": ("神圣历法", "culture", "确立全国祭典之日，民心凝聚", "culture"),
            "学者会": ("兴办学宫", "culture", "延揽学者讲学，识字率缓慢上升", "research"),
            "农民议会": ("均田垦荒", "economy", "重新分配荒地，粮食产量提升", "food"),
        }
        faction = p.get("faction", "农民议会")
        name, slot, desc, effect = templates.get(faction, templates["农民议会"])
        return {"name": name, "slot": slot, "description": desc, "effect": effect}

    # ---------------- 时代叙事

    def _task_era_event(self, p: dict) -> dict:
        texts = {
            "古典": "城邦间开始互派使者，文字被刻在泥板之上，文明步入古典时代。",
            "中古": "城堡与钟楼拔地而起，骑士与僧侣主导着这个中古时代。",
            "文艺复兴": "艺术家重新发现了人的价值，绘画与诗歌在街头巷尾流传，文艺复兴降临。",
            "工业": "蒸汽从作坊里升腾，机器轰鸣彻夜不息，工业时代开启。",
            "现代": "电报线跨越大陆，报纸传入千家万户，现代文明的序幕拉开。",
        }
        era = p.get("era", "古典")
        return {"text": texts.get(era, "一个崭新的时代正在展开。")}

    # ---------------- 奇观效果

    def _task_wonder_effect(self, p: dict) -> dict:
        name = p.get("name", "奇观")
        return {"effect": "food_bonus",
                "text": f"{name} 落成之日，万民朝贺。自此国泰民安，粮产受其庇佑而增益。"}

    # ---------------- 伟人天赋

    def _task_great_person(self, p: dict) -> dict:
        gifts = {
            "scholar": ("大科学家", "其学说使全国研究效率提升", "research"),
            "soldier": ("大将军", "其兵法使士兵在冲突中立于不败", "war"),
            "artisan": ("大建筑师", "其技艺使建造与生产速度倍增", "wealth"),
            "priest": ("大先知", "其教诲使民心长久安定", "stability"),
            "merchant": ("大商人", "其商路使全国财富涌动", "wealth"),
            "farmer": ("大农师", "其农耕之法使粮产丰盈", "food"),
        }
        prof = p.get("profession", "scholar")
        title, gift, kind = gifts.get(prof, ("大贤者", "其智慧泽被后世", "research"))
        return {"title": title, "gift": gift, "gift_kind": kind}

    # ---------------- 远见者奇观立项

    def _task_wonder_launch(self, p: dict) -> dict:
        names = ["通天之塔", "大图书馆", "悬空花园", "永恒灯塔", "巨石祭坛", "星辰观象台"]
        return {"name": self.rng.choice(names)}

    # ---------------- 干预解读

    def _task_interpret(self, p: dict) -> dict:
        event = p.get("event", {})
        text = event.get("text", "")
        words = {1: "吉兆", 0: "考验", -1: "警示"}
        reactions = []
        for r in p.get("reps", []):
            senti = self.rng.choice([-1, 0, 1])
            name = r.get("name", "")
            reactions.append({
                "name": name,
                "interpretation": f"{name} 将「{text}」解读为神明的{words[senti]}",
                "spread_line": f"「{text}」降临了，{r.get('profession', '众人')} {name} 说这是神明的{words[senti]}",
                "sentiment": senti})
        return {"reactions": reactions}

    # ---------------- 国民祈愿

    def _task_prayer(self, p: dict) -> dict:
        prayers = []
        for c in p.get("candidates", []):
            name = c.get("name", "")
            need = c.get("need", "困苦")
            options = [
                ("miracle", "", f"愿神谕垂怜，我正因{need}而煎熬"),
                ("gift", name, f"愿天上赐下恩典，助我摆脱{need}"),
                ("decree", "", f"愿王令革新，让{need}不再折磨我们"),
                ("inspire", "", f"愿智慧之光降临，指点我们摆脱{need}的迷途"),
            ]
            settlement = c.get("settlement", "")
            if settlement:
                options.append(("fund", settlement, f"愿神力注入{settlement}，庇佑我们度过{need}"))
            intent, target, text = self.rng.choice(options)
            prayers.append({"name": name, "text": text, "intent": intent, "target": target})
        return {"prayers": prayers}

    # ---------------- 议会辩论

    def _task_debate(self, p: dict) -> dict:
        pol = p.get("policy", {})
        opp = p.get("opponent", "反对者")
        return {"for": f"「{pol.get('name', '法案')}」利国利民，此刻不施行，更待何时",
                "against": f"{opp} 斥之：此法看似美好，实则动摇国本，当徐徐图之",
                "swing": self.rng.randint(-6, 6)}

    # ---------------- 灾难应对会议

    def _task_council(self, p: dict) -> dict:
        strategies = {
            "food": "组织垦荒与配给，先让所有人吃饱",
            "build": "集中劳力抢修居所与堤防",
            "spirit": "举行安魂仪式，安抚惊惶的民心",
            "safety": "编练巡守队，防止灾后的混乱与劫掠",
        }
        focus = p.get("suggested_focus", "food")
        if focus not in strategies:
            focus = "food"
        leader = p.get("leader", "长者")
        return {"strategy": strategies[focus], "focus": focus,
                "text": f"{leader} 在会上立誓：{strategies[focus]}"}

    # ---------------- 神凡对话

    def _task_commune(self, p: dict) -> dict:
        agent = p.get("agent", {})
        name = agent.get("name", "凡人")
        replies = [
            f"凡人{name}俯首：我听到了神的声音。您所说之事，容我以一生去参悟",
            f"{name} 颤声答道：神明竟垂询于我，此生再无遗憾",
            f"{name} 沉思良久：此事我本有困惑，得神一语，豁然开朗",
        ]
        return {"reply": self.rng.choice(replies), "reaction": "心怀敬畏，久久不能平静"}
