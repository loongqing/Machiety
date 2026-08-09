# 快速开始

本页帮助你在 5 分钟内运行第一个 Machiety 实例。项目提供 **Textual 图形界面** 与 **无头文本** 两种运行方式；即使没有 LLM API Key，也会自动降级为离线 MockLLM，全程可玩。

## 1. 环境要求

- Python **>= 3.11**
- 依赖由 [pyproject.toml](../pyproject.toml) 声明：`textual`、`rich`、`aiohttp`、`numpy`

## 2. 安装

```bash
# 克隆仓库后，在项目根目录
pip install -e .

# 开发/测试（附加 pytest 等）
pip install -e ".[dev]"
```

安装后注册了 `machiety` 命令；也可用 `python -m machiety` 等价运行。

## 3. 配置（可选）

```bash
copy config.toml.example config.toml    # Windows PowerShell / cmd
# cp config.toml.example config.toml    # Linux / macOS
```

编辑 `config.toml`：

```toml
[world]
width = 64        # 世界宽度（格）
height = 40       # 世界高度（格）
settlers = 50     # 开局殖民者数量
# seed = 42       # 不填则每次随机生成新大陆

[llm]
base_url = "https://api.openai.com/v1"   # 任意 OpenAI 兼容接口
api_key = "sk-xxxx"
model = "gpt-4o-mini"          # 大模型：规划 / 裁决 / 顿悟 / 反思
model_small = "gpt-4o-mini"    # 小模型：简单决策 / 批量对话
concurrency = 8                # 并行请求上限
timeout = 60
temperature = 0.8
# economy = true               # 节流模式：LLM 调用量约降 40%~76%
```

> 未填写 `base_url` / `api_key` / `model` 任意一项时，程序自动使用离线 MockLLM（固定种子可复现），不影响任何玩法。

## 4. 启动

### 图形界面模式（推荐）

```bash
machiety
```

首次启动会进入 **「文明的起点」启动选单**：

- 无存档时：为新存档命名（直接回车使用 `autosave`）后进入新世界；
- 有存档时：输入序号或名称载入，输入 `N` 新建世界，输入 `D` 删除存档（需两次确认）。

跳过选单的参数：

```bash
machiety --new MyEmpire     # 直接新开并命名存档（新建即自动保存）
machiety --load MyEmpire    # 直接载入存档
```

进入界面后：地图实时更新，右侧事件日志滚动播报重要事件，顶部状态栏显示纪元、时代、人口与国家精神。界面操作与指令详见[玩法指南](gameplay-guide.md)。

### 无头文本模式

```bash
python -m machiety --headless --days 5 --seed 42
```

流程：打印初始大陆 → 逐日输出人口/存粮/技术/定居点/时代与高亮事件 → 结束后输出「模拟报告」表格（人口、定居点、技术、政策、时代、探索度、LLM 调用统计）。适合脚本化实验与 CI。

## 5. 存档机制速览

- 所有存档集中于 `saves/saves.db`（单文件多槽位）。
- 引擎每 **7 个游戏日** 自动快照一次，失败不影响模拟。
- UI 中输入 `save` / `load` / `saves` / `delete` 管理存档；`quit` / `exit` / `Ctrl+Q` 退出时自动存档。
- 新建世界时会立即自动保存一次（槽位名即你命名的存档）。

## 6. 常用命令行参数

| 参数 | 说明 |
| --- | --- |
| `--headless` | 无头文本模式 |
| `--days N` | 无头模式模拟天数（默认 5） |
| `--seed S` | 世界种子 |
| `--config PATH` | 配置文件路径（默认 `config.toml`） |
| `--load NAME` | 载入存档 |
| `--new [NAME]` | 跳过选单直接新开 |
| `--speed MS` | UI tick 间隔毫秒（默认 350） |
| `--population N` | 开局殖民者人数 |
| `--economy` | LLM 节流模式 |

完整说明见[配置参考](configuration.md)。

## 常见问题

- **Windows 终端乱码**：入口已将 stdout/stderr 切换为 UTF-8；若仍乱码请确认终端（Windows Terminal 推荐）支持 UTF-8。
- **提示「未检测到 LLM 配置」**：属正常降级提示；填写 `config.toml` 后重启即可接入真实模型。
- **找不到存档**：确认存档名与 `saves` 命令列出的槽位一致。
