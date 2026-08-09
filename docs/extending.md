# 扩展指南

Machiety 的模块化设计提供了清晰的扩展点。本页列出常见扩展场景的落点与注意事项。所有扩展都应遵守：离线 MockLLM 可用、事件总线广播、存档往返一致。

## 1. 新增玩家指令

三处必改：

1. `machiety/commands/parser.py`：命令名加入 `COMMAND_NAMES`，`HELP_TEXT` 补说明；
2. `machiety/commands/effects.py`：`execute_command` 新增分支——参数校验失败返回用法提示；成功后修改状态并 `bus.publish`；
3. `tests/test_commands.py`：补解析用例。

耗时逻辑（如大跨度快进）建议分片执行或在 UI 提供反馈；当前无权限模型与撤销栈，如需回滚可在效果函数内自行保存变更前状态。

## 2. 新增灾难类型

- `machiety/engine/scheduler.py`：灾难名称映射、持续时间与结算逻辑（正午 `_disasters_tick`）。
- `commands/effects.py` 的 `disaster` 分支校验新类型。
- 发布 `disaster` 事件（自动进入 UI 通知集合）。
- 参考 `tests/test_batch_features.py` 的干旱测试：布置地形/存粮/角色 → `unleash_disaster` → 推进到结算点 → 断言资源与需求变化。

## 3. 新增区域类型（城市）

- `machiety/civilization/city.py`：居民主导需求 → 区域类型的映射表，以及成本常量。
- `fund` 指令自动支持（区域类型参数透传）。
- 区域落成事件由城市系统统一发布。

## 4. 新增科技类别 / 调整传播

- `machiety/civilization/tech.py`：灵感池键（类别名）、顿悟阈值、传播公式（识字率×道路因子）、`bonus` 关键词匹配。
- 若新增类别，同步 `effects.py` 的 `DOMAIN_ALIASES` 别名映射。

## 5. 新增政策槽位 / 派系

- `machiety/civilization/policy.py`：槽位列表、派系定义、提案权重与动荡阈值（decree 当前 +12）。
- 注意槽位互斥语义与 `spirit` 国家精神合成逻辑。

## 6. 新增 LLM 任务类型 / 自定义后端

- 新任务：约定 `task` 名 → `llm/prompts.py` 构建消息 → `llm/mock.py` 添加 `_task_<name>` 处理器（离线可用是硬性要求）→ 调用方用 `parse_json_loose` 解析。
- 新后端：继承 `BaseLLM` 实现 `generate`，在 `__main__.build_llm` 按条件构造；异常路径必须能返回可用结果。

## 7. 新增智能体行为

- `machiety/agents/manager.py`：`_plan` 的 prompt 中声明新 action；`_execute` 添加分支（需求变化、库存/世界交互、事件发布）。
- `llm/prompts.py` 与 `llm/mock.py` 同步支持新 action。

## 8. 修改存档结构

1. 更新 `Game.to_save_dict` / `from_save_dict`（缺失字段给默认值）；
2. 如需新表/新列：`persistence/db.py` 补 schema 与缺失列迁移；
3. 提升 `saver.py` 的 `schema_version` 并确认 `_check_version` 行为；
4. 在 `test_persistence.py` / `test_batch_features.py` 补往返与版本用例。

## 9. UI 扩展

- 新组件：在 `app.py` 的 `compose` 中声明，样式写入 `styles.tcss`（记住：单行 widget 不加 border）。
- 新事件渲染：`EventLog` 图标映射补 kind；需要浮层通知的加入 `NOTIFY_KINDS`。
- 新键位：`BINDINGS` 添加 Binding 并实现 `action_xxx`。

## 通用检查清单

- [ ] MockLLM 下功能完整可用（无网络可玩）
- [ ] 重要变化通过 `bus.publish` 广播
- [ ] 新状态字段完成存档往返
- [ ] 新增/修改逻辑有对应测试（离线、固定种子）
- [ ] `HELP_TEXT` 与相关文档同步更新
