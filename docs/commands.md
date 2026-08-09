# 命令系统

命令子系统由「解析层 + 效果层 + UI 输入层 + 事件总线」构成：`machiety/commands/parser.py`（解析）、`machiety/commands/effects.py`（执行）、`machiety/ui/command_bar.py`（输入）、`machiety/engine/events.py`（广播）。

## 数据流

```mermaid
sequenceDiagram
participant CB as CommandBar
participant APP as MachietyApp
participant PAR as parse_command
participant FX as execute_command
participant G as Game 及子系统
participant E as EventBus
CB->>APP : 提交输入
APP->>PAR : 解析文本
PAR-->>APP : Command(name, args, raw)
APP->>FX : 执行
FX->>G : 读写状态（世界/城市/科技/政策/存档…）
FX->>E : publish(事件)
FX-->>APP : CommandResult(text, new_game?)
alt load 返回新 Game
APP->>APP : set_game(new_game)
end
APP-->>CB : 显示回执并记录历史
```

## 解析器（parser.py）

- 基于 `shlex` 分词，支持引号参数；`ValueError` 时回退为空白分词；空输入返回 `None`。
- 输出 `Command(name, args, raw)`，命令名统一小写。
- `COMMAND_NAMES` 白名单驱动 Tab 补全：

```python
["watch", "miracle", "disaster", "inspire", "gift", "decree", "fund",
 "launch", "honor", "skip", "map", "epoch", "policy", "spirit",
 "wonders", "tech", "status", "history", "avatar", "prayers", "talk",
 "save", "load", "saves", "delete", "quit", "exit", "help"]
```

- `HELP_TEXT` 是 `help` 指令与应用启动欢迎页的内容来源。

## 效果执行器（effects.py）

`execute_command(game, cmd) -> CommandResult(text, new_game=None)`，按命令名分支：

- 参数校验失败 → 返回用法提示，不修改状态。
- 成功 → 修改状态并 `bus.publish` 广播，UI 实时可见。
- **位置解析**：支持「定居点名」或 `x,y` 坐标；越界或不存在返回错误提示。
- **load 特例**：返回 `CommandResult(new_game=...)`，由 UI 整体替换 Game 实例。

命令分类：

| 类别 | 命令 | 要点 |
| --- | --- | --- |
| 世界干预 | `disaster` / `miracle` / `inspire` / `gift` / `decree` / `fund` / `launch` / `honor` / `avatar` | 干预指令会触发反应链（`ReactionEngine.on_intervention`）并结算祈愿恩宠；miracle 写入全体记忆且可能「曲解」；inspire 支持领域别名映射（DOMAIN_ALIASES）；decree 含「宣战」触发战争 |
| 神民互动 | `prayers` / `talk` | prayers 列出待回应的祈愿；talk 与角色对话（LLM `commune` 任务） |
| 状态查询 | `status` / `watch` / `map` / `epoch` / `policy` / `spirit` / `wonders` / `tech` / `history` | watch 开启/取消侧栏追踪 |
| 系统控制 | `skip` / `save` / `load` / `saves` / `delete` / `quit` / `exit` | skip 调用 `Game.skip_days`；quit 自动存档后退出 |

### 祈愿与恩宠

国民每日可能向天祈愿（`PrayerBoard.daily`，LLM `prayer` 任务，intent 限定 miracle/gift/disaster/decree/fund/inspire）。`prayers` 查看未决祈愿；玩家执行匹配的干预指令后 `try_grant` 按「intent + target」命中，祈愿者获恩宠（自我实现 +0.2、影响力 +1、核心记忆）。7 日未回应自动消散。

### talk 神凡对话

`talk <角色名> "话语"` 调用 LLM `commune` 任务，payload 含角色档案与按话语检索的相关记忆；回复展示给玩家，角色记住这次对话（importance 7.0 晋升核心记忆）。LLM 失败时降级为模板回应。

### 灵感领域别名

`inspire idea <领域> "概念"` 通过 `DOMAIN_ALIASES` 映射：

- 粮食：food、粮食、农业、食物
- 战争：war、战争、军事、战斗
- 精神：spirit、精神、信仰、文化
- 经济：economy、经济、贸易、商业
- 建造：build、建造、建筑、工程

未指定或未识别领域时随机选择现有技术的领域。

## 存档命令与槽位

- `save [名称]`：写入 `saves/saves.db` 的指定槽位；缺省覆盖当前槽位（`game.current_slot` 自动跟踪）。
- `load [名称]`：按槽位名加载（缺省 `autosave`），失败时列出可用存档。
- `saves`：列出全部槽位（进度、时代、人口、更新时间）。
- `delete <名称>`：删除槽位；删除当前槽位时清空引用。
- `quit` / `exit`：先 `save_current()` 再退出。

## UI 集成（command_bar.py）

- 输入框提交触发 `Input.Submitted`；↑/↓ 回溯历史（`record` 去重、上限 100 条、维护草稿与指针）。
- Tab 补全基于 `COMMAND_NAMES` 前缀匹配。

## 性能与故障排查

- 解析开销极低（分词 + 字符串操作）；`skip` 大跨度注意 CPU 占用，可分批反馈。
- 未知命令返回「未知指令」提示；`help` 查看全部用法。
- 模拟异常由 UI 捕获并通知，不影响进程。

## 新增命令清单

1. `parser.py`：加入 `COMMAND_NAMES` + 更新 `HELP_TEXT`；
2. `effects.py`：`execute_command` 新增分支（参数校验 → 状态修改 → 事件发布）；
3. `tests/test_commands.py`：补解析用例。
