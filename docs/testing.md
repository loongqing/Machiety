# 测试指南

测试位于 `tests/`，使用 pytest 框架。**全部测试离线可跑**：基于 `MockLLM(seed=...)` 与固定世界种子，无需网络与 API Key。

```bash
python -m pytest tests -q                # 全部测试
python -m pytest tests/test_world.py -q  # 单文件
```

## 测试金字塔

```text
        ┌──────────────┐
        │ UI 冒烟测试   │  test_ui_smoke.py
        ├──────────────┤
        │ 集成测试      │  test_persistence.py、test_batch_features.py
        ├──────────────┤
        │ 单元测试      │  test_world / test_memory / test_commands / test_policy
        └──────────────┘
```

## 各测试文件说明

| 文件 | 类型 | 覆盖内容 |
| --- | --- | --- |
| `test_world.py` | 单元 | 地形边界与陆地比例、种子确定性、出生点可通行、资源存在性 |
| `test_memory.py` | 单元 | 记忆检索相关性（相似度×时近衰减×重要性）、核心记忆晋升、观察容量上限、序列化往返 |
| `test_commands.py` | 单元 | 全部指令解析（引号参数、大小写不敏感、空输入返回 None） |
| `test_policy.py` | 单元 | 四槽位互斥、decree 副作用与动荡值上升、历史长度 |
| `test_persistence.py` | 集成 | 模拟运行冒烟 + 存档往返一致性（seed/clock/agents/核心记忆） |
| `test_ui_smoke.py` | 冒烟 | Textual 挂载渲染、暂停/移动/查看/追踪键位、命令执行与历史回溯 |
| `test_batch_features.py` | 集成 | 干旱灾难结算、编年史与新字段（prophet/ruins/foreign）往返、城邦宣战与兼并、节流模式事件生成、存档版本化（SaveVersionError） |
| `_scroll_check.py` | 手动脚本 | InfoPanel 垂直/水平滚动验证（下划线开头，不被 pytest 收集） |

## 编写约定

1. **固定种子与临时目录**：世界与 LLM 均传入固定 seed；存档测试用 `tmp_path` 隔离，避免污染 `saves/`。
2. **异步测试**：引擎方法为 async，测试用 `asyncio.run(...)` 或 pytest-asyncio 风格包装；UI 测试用 `app.run_test(size=(120, 36))` 并 `await app.wait_for_background_tasks()` / `pause()` 控制事件循环。
3. **控制 LLM 输出**：需要裁决特定结果时，构造 `BaseLLM` 测试子类直接返回所需 dict（参考 `test_batch_features.py` 的 WinningLLM），不要依赖真实网络。
4. **存档必测往返**：任何新增字段/结构，save → load 后断言一致；schema 变更需更新版本常量并新增版本校验用例。
5. **UI 断言**：优先断言组件存在性、`app.last_result` 文本与命令历史，避免脆弱的像素级断言；注意焦点管理（命令栏聚焦后再输入）。
6. **灾难/战争类测试**：精确控制时钟（推进到正午触发 `_disasters_tick` 等结算点），断言数值变化方向而非精确值（保留随机性空间）。

## CI 建议

- 直接运行 `python -m pytest tests -q`；UI 冒烟对终端尺寸敏感，保持 120×36。
- 大规模世界生成与长周期模拟属慢速场景，按需标记并单独分组。
- 可引入 pytest-cov 设置覆盖率门禁；关键模块（parser、saver、policy）建议保持高覆盖。

## 常见排查

- **UI 冒烟不稳定**：多为焦点或异步时序问题——先 `pause()` 等待挂载完成，再模拟按键。
- **存档失败**：确认测试使用临时 `save_dir`；检查新字段是否在 `to_save_dict` / `from_save_dict` 双向处理。
- **世界生成断言失败**：确认 RNG 隔离（不同用途使用独立 RNG），避免测试间相互污染。
