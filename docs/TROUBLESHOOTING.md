# 排障与验收

## Bot 群里收不到消息

依次检查：Bot 是否仍在群里、群 ID 是否在白名单、路由模式是否为 `muted/mentions`、是否 @ 了正确 username、BotFather Privacy Mode 是否符合预期。修改 Privacy Mode 后把 Bot 移出群再加入。

## Bot-to-bot 没有触发

私聊先确认发送方和接收方都在 BotFather 开启 Bot-to-Bot Communication Mode，并确认发送目标是接收 Bot 的完整 `@username`。群聊使用 `/command@TargetBot` 或直接 Reply 接收 Bot；若希望 Telegram 交付未点名的 Bot 消息，接收 Bot 还需是管理员或关闭 Group Privacy Mode，但本桥会继续静默丢弃未定向消息。再核对双方是否都配置在同一桥实例、`getMe` 是否成功，以及 rolling pair budget 或当前 causal epoch 总预算是否已达到上限；所有者可在群内运行 `/flow_status`。不要用显示名或消息正文冒充 numeric bot ID。

## 日志出现 409 Conflict

同一个 Token 有另一个 `getUpdates` 消费者。检查旧 systemd 服务、测试进程、Docker 容器和开发机；停掉重复消费者。Webhook 与 long polling 也不要混用。

## Agent 回答正常但 Telegram 没收到

先在对应 Bot 私聊发送 `/delivery`。若结果已经是 `generated`，只重试 Telegram 发送；若已是 `dead`，修复根因后用 `/retry_update <update_id>` 重新入队。核对网络、Bot 是否被踢出群、thread/reply 目标是否有效、文本是否超限。

## 新群里 Bot 完全不响应

先在该 Bot 私聊发送 `/pending_groups`，完成可信群/外部群审批；再用 `/groups` 核对状态。待审批群不会调用 Agent，这是默认安全行为。

## 收到群异常私聊提醒

提醒只展示群标签和错误类别，不含聊天正文。问题持续时点“暂停该群”，修复后在对应 Bot 私聊打开 `/agent_switch` 恢复该群；也可用 `/agent_resume_group <chat_id>`。

## 一直显示 typing

typing 刷新任务没有在 `finally` 取消，或子进程超时后仍未退出。确保成功、失败、超时和 `/stop` 四条路径都终止 refresh task 和整个子进程组。

## GIF/贴纸说“没有可用素材”

这通常不是发送 API 故障。先在需要使用的同一个 Bot、同一个聊天里发一次素材，让桥生成 chat-scoped `asset_id`；或将审核后的文件放进该 Agent 的 `.telegram-media`。不要直接把别的私聊得到的 `file_id` 塞给模型。

## 文档已收到但 Agent 看不到

记录并比较桥保存路径、文件属主/权限、runner 实际 Linux 用户和 Agent 沙箱根目录。需要时只把本次文件复制到短期镜像目录，不扩大整个文件系统权限。

## 重启后重复回复

核对四个时间点的日志：inbox commit、offset advance、outbox generated、Telegram sent。若模型再次运行，通常是生成结果没有先提交或启动恢复把 `processing` 错当成新消息。恢复规则应为：无缓存结果才重新处理；已有缓存结果只重放发送。

## 群里认错人

抓取该回合的结构化 envelope，确认 `from.id`、`reply_to_message.from.id`、quoted message 和 recent speaker 是否保留。禁止把整理后的自然语言 transcript 当唯一证据。修正后清除由错误身份推导出的摘要。

## 上线前的故障注入

- 收到 update 后、写 inbox 前退出：Telegram 应重新投递。
- inbox commit 后、推进 offset 前退出：幂等键应阻止重复处理。
- Agent 生成后、写 outbox 前退出：允许重新调用一次。
- outbox commit 后、Telegram send 前退出：只重放缓存结果。
- Telegram send 成功但本地未标记完成时退出：使用发送操作关联和保守重试策略，监控潜在重复。
- 连续制造模型失败：达到阈值后熔断，群聊不应无限堆积。

## 最小可观测字段

建议日志只保留：时间、bot key、update ID、chat 类型、thread ID、路由结果、处理阶段、Agent key、耗时、重试次数、错误类别。不要记录 Token、完整正文、完整 prompt 或模型完整输出。
