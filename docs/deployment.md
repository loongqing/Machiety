# 部署指南

Machiety 的典型生产用途：无头模式长时间模拟、批量实验与离线评估。UI 模式面向交互终端。本页给出部署与运维建议。

## 服务器要求

- 操作系统：Linux（Ubuntu 22.04+ 等）或 Windows；UI 模式需要支持 UTF-8 的终端。
- Python：>= 3.11。
- 资源：CPU 多核利于并发 LLM 规划；内存 4~8GB 视世界规模；磁盘 ≥ 5GB（代码、依赖、存档）。
- 网络：访问 OpenAI 兼容 API（未配置则离线运行）。

## 安装与配置

```bash
python -m venv .venv
.venv/bin/pip install -e .
cp config.toml.example config.toml     # 填写 [world] 与 [llm]
```

- 配置加载直接读取 TOML，不读取环境变量；如需注入密钥，请在部署脚本中用模板渲染生成 `config.toml`。
- `config.toml` 含密钥：仅对运行账户可读；`saves/` 目录需可写。
- 运行账户：使用专用低权限账户。

## 无头批处理部署

适合长周期模拟与实验：

```bash
machiety --headless --days 30 --seed 42 --config /etc/machiety/config.toml >> /var/log/machiety.log 2>&1
```

- 非交互环境下启动选单自动跳过，直接新开世界。
- 退出时自动静默存档（atexit 兜底），存档写入配置的 `save_dir`。
- 批量实验：遍历种子列表逐个运行；从终局报告解析人口/技术/时代指标归档。
- cron 示例：`0 2 * * * /usr/bin/machiety --headless --days 1 --config /etc/machiety/config.toml >> /var/log/machiety.log 2>&1`

## 服务化（systemd 示例）

```ini
[Unit]
Description=Machiety headless simulation
After=network-online.target

[Service]
User=machiety
WorkingDirectory=/opt/machiety
ExecStart=/opt/machiety/.venv/bin/machiety --headless --days 365 --config /opt/machiety/config.toml
Restart=on-failure
StandardOutput=append:/var/log/machiety.log
StandardError=append:/var/log/machiety.log

[Install]
WantedBy=multi-user.target
```

## Docker 容器化（概念性）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
COPY machiety ./machiety
RUN pip install --no-cache-dir .
CMD ["machiety", "--headless", "--days", "10"]
```

要点：

- `saves/` 挂载宿主机卷以持久化存档（全量备份 = 复制 `saves/saves.db`）。
- 配置通过挂载 `config.toml` 或在构建时注入。
- 健康检查：短天数无头运行校验配置与 LLM 连通性。
- 重启策略 `on-failure`，配合日志轮转。

## 性能调优

| 手段 | 说明 |
| --- | --- |
| `concurrency` | 按 API 限流与 CPU 调整并发上限 |
| `model_small` | 简单决策用小模型，降低成本与延迟 |
| `economy = true` | 节流模式：规划缓存 + 分组反思，调用量约降 40%~76% |
| `timeout` / `max_tokens` | 避免长尾请求阻塞；控制响应体积 |
| 世界尺寸 | 大地图提升生成与查询开销，按需求取舍 |
| `--speed` | UI 模式调整 tick 间隔平衡流畅度与 CPU |

## 监控与运维

- 关键指标：`game.stats()` 输出的人口、存粮、技术、定居点、时代；`llm.calls` / `llm.fallbacks`（无头报告与 `status` 指令可见）。
- 告警建议：人口骤降、存粮不足、fallbacks 比率异常升高。
- 日志：控制台 rich 输出重定向到文件或 journald；定期轮转。
- 备份：定期复制 `saves/saves.db`；损坏时用最近可用槽位恢复。
- 安全：仅允许出站访问 API 域名；密钥用 KMS/Vault 管理，勿硬编码进镜像。

## 故障排查速查

| 现象 | 排查 |
| --- | --- |
| LLM 频繁降级 | 网络/配额/限流；调低 concurrency、检查 base_url 与 api_key |
| 模拟卡顿 | 降低并发、增大 timeout、缩小世界规模；UI 模式先暂停再排查事件日志 |
| 存档无法载入 | 版本不匹配（SaveVersionError）或槽位名错误；`saves` 列出可用槽位 |
| 终端乱码 | 确认终端支持 UTF-8（入口已自动 reconfigure stdout/stderr） |
