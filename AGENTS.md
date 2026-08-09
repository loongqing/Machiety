# AGENTS.md

本文件面向在本仓库工作的 AI 编码代理（及新加入的开发者），说明项目结构、常用命令、代码约定与已知陷阱。完整用户/开发文档见 [`docs/`](docs/README.md)。

## 项目一句话说明

Machiety 是一个 LLM 驱动的命令行虚拟国家模拟游戏：Textual TUI + asyncio 引擎，数百个智能体在网格世界中自主演化，玩家以「超越存在」身份通过神谕/法令/灾难间接干预。Python >= 3.11。

## 常用命令

```bash
# 安装（开发模式 + 测试依赖）
pip install -e ".[dev]"

# 运行（UI 模式；非交互环境会自动跳过启动选单）
python -m machiety

# 无头模拟（CI/脚本友好，不进 UI）
python -m machiety --headless --days 5 --seed 42

# 运行全部测试（离线，无需网络/API Key，固定种子可复现）
python -m pytest tests -q

# 运行单个测试文件 / 单个用例
python -m pytest tests/test_world.py -q
python -m pytest tests/test_world.py::test_deterministic -q
```

注意：用户 shell 为 Windows PowerShell，不支持 `&&` 连接符，请使用 `;` 分隔多条命令。

## 架构地图（改代码前先看哪里）

| 要改的功能 | 入口文件 |
| --- | --- |
| CLI 参数 / 启动选单 / 无头报告 | `machiety/__main__.py` |
| 配置项（config.toml） | `machiety/config.py` + `config.toml.example` |
| 时间推进 / 灾难 / 生死 / 自动快照 | `machiety/engine/scheduler.py`（`Game`） |
| 干预反应链 / 祈愿板 / 灾难应对会议 | `machiety/engine/reaction.py`（`ReactionEngine`、`PrayerBoard`） |
| 地形生成 / 资源 / 迷雾 | `machiety/engine/world.py` |
| 事件广播（UI 日志与通知来源） | `machiety/engine/events.py`（`EventBus`） |
| 智能体行为 / 批量对话 / 冲突触发 | `machiety/agents/manager.py` |
| 记忆三层结构 / 检索 / 遗忘 | `machiety/agents/memory.py`（依赖 `machiety/embed/store.py` 自研哈希嵌入） |
| 科技顿悟 / 政策投票 / 城市 / 伟人 / 奇观 / 时代 | `machiety/civilization/*.py` |
| LLM 调用 / 降级 / 提示词 | `machiety/llm/base.py`、`openai_client.py`、`mock.py`、`prompts.py` |
| 玩家指令解析 | `machiety/commands/parser.py`（`COMMAND_NAMES`、`HELP_TEXT`） |
| 玩家指令效果 | `machiety/commands/effects.py`（`execute_command` 分发） |
| 存档读写 / 槽位管理 | `machiety/persistence/saver.py`、`db.py` |
| UI 布局 / 键位 / tick | `machiety/ui/app.py`（样式在 `machiety/ui/styles.tcss`） |

关键数据流：UI tick → `Game.step()`（每小时）→ 智能体并行规划（LLM）→ 子系统每日结算 → `EventBus.publish` → UI 日志/通知。

## 代码约定

- **语言与风格**：Python 3.11+，中文注释与 docstring；`from __future__ import annotations`；优先使用 dataclass。
- **异步**：LLM 调用、智能体规划、`Game.step` 均为 async；并发用 `asyncio.gather`，并发上限由 `config.llm.concurrency` 的信号量控制。
- **无重依赖原则**：不引入 Chroma/FAISS/sentence-transformers 等向量库——记忆检索使用 `machiety/embed/store.py` 的自研哈希嵌入 + 余弦相似度。配置解析只用内置 `tomllib`，不引入 pydantic/toml 第三方库。
- **LLM 降级是硬性要求**：任何 LLM 调用路径必须能在 MockLLM 下完整工作；所有测试必须离线可跑（用 `MockLLM(seed=...)` 保证可复现）。
- **宽容 JSON 解析**：解析 LLM 输出一律用 `BaseLLM.parse_json_loose`，不要直接 `json.loads`。
- **事件解耦**：子系统不直接操作 UI；重要变化统一 `bus.publish(kind, text, tick, x, y, **data)`。UI 中 `NOTIFY_KINDS` 决定哪些事件弹浮层通知。
- **循环导入**：`Game` 的引用在子模块中一律放在 `TYPE_CHECKING` 块内，运行时按需局部导入。

## 新增一条玩家指令的固定流程（三处必改）

1. `machiety/commands/parser.py`：把命令名加入 `COMMAND_NAMES`（Tab 补全依赖它），并在 `HELP_TEXT` 中补充说明。
2. `machiety/commands/effects.py`：在 `execute_command` 中添加分支；参数校验失败返回用法提示；副作用通过 `bus.publish` 广播。
3. `tests/test_commands.py`：补充解析测试。

## 已知陷阱（历史踩坑，勿重复）

- **Textual `height: 1` + `border` 冲突**：给 1 行高的 widget 加 border 会挤掉内容导致不可见；需要边框时用 `outline`/增加高度，或去掉 border。
- **Textual 鼠标点击坐标**：`Click.offset` 是含边框/内边距的坐标，映射到内容区域前必须减去 `content_offset`，否则点击定位偏移。
- **地图像素风渲染**：主地图采用「半块字符 2×2 像素 + 叠加符号」方案（见 `map_view.py`）；资源叠加符号仅在 `cell_width=2` 模式下渲染，避免错位。
- **Windows 终端编码**：`__main__.py` 已将 stdout/stderr reconfigure 为 UTF-8；不要在别处改回默认 GBK。
- **退出存档去重**：UI 模式不注册 atexit 自动存档（`quit` 指令与 Ctrl+Q 已在 `action_quit` 中保存），避免重复写入同一槽位；只有无头模式注册 `_save_quietly`。

## 测试约定

- 测试位于 `tests/`，使用 pytest + 固定 seed + 临时目录（`tmp_path`）隔离存档。
- UI 测试用 Textual 的 `app.run_test(size=(120, 36))`，注意焦点管理与 `pause()` 等待异步。
- 涉及 LLM 行为的测试如需控制裁决结果，构造自定义 `BaseLLM` 子类（参考 `tests/test_batch_features.py` 的 WinningLLM）。
- 存档测试必须覆盖往返一致性（save → load → 断言 seed/clock/agents/记忆一致）。
- `tests/_scroll_check.py` 以下划线开头，是按需运行的验证脚本，不被 pytest 自动收集。

## 存档与运行时产物

- 所有存档集中在 `saves/saves.db`（单文件多槽位，`save_slots` 表）；旧版独立 `.db` 文件仅只读回退。
- `config.toml` 与 `saves/` 已被 gitignore，不要提交玩家的配置与存档。
- 存档 schema 版本存于 `meta.schema_version`；改存档结构时同步更新 `saver.py` 的版本常量与 `_check_version`，并补往返测试。
