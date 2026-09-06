# 真实痛点与解决办法

| 现象 | 常见根因 | 我们的处理 |
|---|---|---|
| “正在处理……”过一会儿变成答案 | 先发占位消息，再 `editMessageText` | 只发 `typing` 状态，最终答案一次发送 |
| 私聊正常，群里不理人 | Privacy Mode、群不在白名单或路由模式不匹配 | 检查 BotFather 设置；显式群白名单；提供四种群模式 |
| 三个 Agent 抢着回答 | 每个 Bot 独立判断，没有统一认领 | 中央路由按 @、回复、别名认领；共享命令全局去重 |
| Bot-to-bot 仍靠桥伪装转发 | 沿用了 Bot API 10.0 以前的限制 | 开启 BotFather 的 Bot-to-Bot Communication Mode；使用原生私聊 username、群 command mention/Reply，并以 numeric bot ID 鉴权 |
| 把群友认成主人，或把两个人合成一人 | 只把群聊压成一段文本；昵称会变；丢失回复边 | numeric user ID 主键、结构化 reply graph、人物表和输出身份守卫 |
| 用户已经纠正，Agent 还沿用旧理解 | 错误摘要仍在历史上下文 | 记录纠正事件，废弃旧解析，按原始消息重新解析 |
| 重启后重复回答或丢消息 | offset、模型调用和发送没有事务边界 | SQLite inbox/outbox；update 先落盘；生成结果可重放 |
| `/stop` 按了没反应 | 模型子进程阻塞了轮询协程 | 模型独立任务/进程组，控制命令始终可处理 |
| 群里 Bot 无限互相“收到” | 每条 Bot 输出都触发下一 Bot | 调用前持久化 pair 与 causal-epoch 双预算、只接收定向命令/Reply、低价值回复静默、旧 epoch 结果丢弃 |
| 另一个 Agent 下次被叫醒时不知道群里刚说过什么 | 各 Agent 只保存自己的输出 | 把已发送文本写入其他 Agent 的同群同 Topic 被动上下文，但不唤醒它们 |
| Telegram Topic 回错楼 | 发送时漏了 `message_thread_id` | 文本和媒体全链路保存 thread ID |
| 文件下载了，Agent 却说看不到 | 桥账号与 Agent 账号权限不一致 | 公共父目录只允许 traversal，精确文件授权；必要时复制到短期镜像目录 |
| ZIP 能读但存在安全风险 | 直接 `extractall` | 拒绝路径穿越、绝对路径、链接和特殊文件；限制数量与展开体积 |
| 声称支持 GIF，Agent 却说“发不了” | 发送通道存在，但没有可用素材；群聊又禁止任意联网下载 | 从同一聊天登记过的 GIF 复用，或预先放入受控媒体库 |
| 贴纸的 `file_id` 被提示词滥用 | 模型可构造任意 Telegram 标识 | 桥把真实 `file_id` 换成按 bot+chat 绑定的不透明 `asset_id` |
| 图片/文档在外部群泄露 | 把私聊文件权限照搬到所有群 | 私聊、可信群、外部群三档附件策略；外部群仅同聊天资产 |
| 有时整条答案发送失败 | Telegram Markdown 转义错误或文本过长 | 纯文本清理与安全分段，不依赖脆弱 parse mode |
| 日志里出现聊天内容或 Token | 记录了原始 payload、prompt、命令环境 | Token 和正文永不入日志；完成后清除原始 payload |
| `409 Conflict` | 同一个 Token 同时跑了两个 `getUpdates` | 每 Token 只允许一个消费者，部署前停旧服务 |
| 发语音后 Agent 猜内容 | 桥只下载音频，没有可靠转写器 | 固定本地转写 wrapper；失败显式标记，不猜测 |
| 临时关掉 Agent 必须改配置重启 | 群模式只有静态配置 | owner-only 动态模式与 Agent 总闸，SQLite 持久化 |
| 没必要长篇回复，但完全沉默像掉线 | 没有轻量确认通道 | `NO_REPLY` 配默认 Reaction，或由 Agent 请求具体 Reaction |
| Bot 被拉进陌生群后立即开始工作 | 只信静态白名单或默认放行 | 新群进入待审批；owner 私聊选择可信群或外部群 |
| 某个群出错，只能停掉整个 Agent | 缺少按 Agent+群的熔断 | 异常脱敏私聊提醒；一键暂停故障群；其他群和私聊保留 |
| 连续失败后不知道卡在哪里 | 死信只留在数据库 | 私聊 `/delivery` 看 update ID 和错误类别，`/retry_update` 显式重试 |

## 素材能力最容易被误会

一个 Agent 是否“能发 GIF”由两件独立的事决定：

1. 桥是否实现了 `sendAnimation` / `sendSticker` / `sendPhoto`。
2. Agent 是否有一个允许使用的素材来源。

只完成第 1 项，Agent 仍然会诚实地说没有 GIF 可发。我们的默认做法是：主人在目标私聊或群聊中先发一次素材，桥登记为该 `bot + chat` 专属资产；或者管理员把审核过的素材放进该 Agent 的 `.telegram-media`。不默认开放“去网上随便搜并下载”。
