# 配置参考

Machiety 的配置由两部分组成：`config.toml` 文件（世界参数与 LLM 后端）与命令行参数（运行时覆盖）。

## config.toml

配置文件默认路径为工作目录下的 `config.toml`，可用 `--config PATH` 指定。文件不存在时所有配置取默认值（离线 Mock 模式）。示例见 [config.toml.example](../config.toml.example)。

### `[world]` 世界参数

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `width` | int | 64 | 世界宽度（格数），影响生成耗时与内存 |
| `height` | int | 40 | 世界高度（格数） |
| `settlers` | int | 50 | 开局殖民者数量 |
| `seed` | int | 随机 | 世界种子；相同种子生成相同大陆，且静态地形可由种子重建（存档只存动态变化） |

### `[llm]` LLM 后端

| 键 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `base_url` | str | 空 | 任意 OpenAI 兼容接口地址（末尾 `/` 会被去除） |
| `api_key` | str | 空 | API Key；占位符 `sk-xxxx` 视为未配置 |
| `model` | str | 空 | 大模型，用于规划、裁决、顿悟、反思等复杂任务 |
| `model_small` | str | 同 `model` | 小模型，用于简单决策与批量对话，降低成本与延迟 |
| `concurrency` | int | 8 | 并行请求上限（信号量控制） |
| `timeout` | float | 60.0 | 单次 HTTP 超时（秒） |
| `temperature` | float | 0.8 | 采样温度 |
| `max_tokens` | int | 600 | 单次响应最大 token |
| `thinking` | bool | false | 思考模式：请求附带 `enable_thinking`（true 时同时启用流式输出，兼容 Qwen3 等混合思考模型）；不支持该参数的接口会忽略此字段 |
| `economy` | bool | false | 节流模式：规划缓存 + 分组反思，LLM 调用量约降 40%~76% |

**可用性判定**：`base_url`、`api_key`、`model` 三者均非空时视为已配置真实 LLM；否则（以及运行时任何调用失败重试耗尽后）自动降级为离线 MockLLM。降级不中断模拟。

## 命令行参数

入口 `machiety`（等价 `python -m machiety`）：

| 参数 | 说明 |
| --- | --- |
| `--headless` | 无头文本模式，不进入 Textual UI，结束后输出模拟报告 |
| `--days N` | 无头模式模拟天数，默认 5 |
| `--seed S` | 世界种子；未指定时回退到 `config.toml` 的 `seed`，仍未指定则随机 |
| `--config PATH` | 配置文件路径，默认 `config.toml` |
| `--load NAME` | 载入指定存档槽位；找不到时退出并提示 |
| `--new [NAME]` | 跳过启动选单直接新开世界；可选值为新存档命名（缺省 `autosave`），新建即自动保存 |
| `--speed MS` | UI tick 间隔（毫秒），覆盖默认 350ms；下限 20ms |
| `--population N` | 开局殖民者人数，覆盖 `[world].settlers`（最小为 1） |
| `--economy` | 启用 LLM 节流模式（等价 `economy = true`） |

**参数优先级**：命令行参数 > `config.toml` > 内置默认值。

## 运行模式行为差异

| 行为 | UI 模式 | 无头模式 |
| --- | --- | --- |
| 启动选单 | 交互式选单（`--load`/`--new` 跳过） | 直接新开 |
| 时间推进 | 每 tick（默认 0.35s）推进 1 游戏小时 | 连续推进 `24 × days` 小时 |
| 退出自动存档 | `quit`/`exit`/Ctrl+Q 时保存 | 进程退出时静默保存（atexit 兜底） |
| 非交互环境（管道/CI） | 自动跳过选单直接新开 | — |

## 相关代码

- 配置加载：`machiety/config.py`（`GameConfig` / `LLMConfig` / `load_config`，基于内置 `tomllib`）
- 入口与参数解析：`machiety/__main__.py`
