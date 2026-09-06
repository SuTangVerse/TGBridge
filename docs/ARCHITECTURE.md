# 架构与消息生命周期

## 1. 一条更新如何走完

```text
getUpdates
  → 原始 update 写入 inbox 并提交
  → 推进该 Bot 的 offset
  → 解析发送者、chat、thread、reply、附件
  → 鉴权和路由
  → 构造结构化上下文
  → 在独立任务中运行 Agent
  → 文本/媒体结果写入 outbox 并提交
  → 调用 Telegram 发送
  → 标记完成并清除不再需要的原始 payload
```

关键顺序不能颠倒：先持久化 update 才推进 offset；先持久化回复才调用发送接口。这样宕机发生在任何一步，都能判断应该重试处理还是只重放已生成结果。

建议状态机：

```text
received → processing → done
                    ↘ retry → dead

reply: none → generated → sent
```

处理或交付连续失败五次后进入 `dead`。所有者可从私聊查看该 Bot 的死信 update ID；仅当原始 payload 尚在保留期内，才能显式重置尝试次数并重新入队。

幂等键至少包含 `bot_key + update_id`。一次操作发出的文字和多项媒体都记录在同一个 outbox 操作下。

## 2. 路由

人类私聊只接受 `OWNER_IDS`；配置内 Bot 的原生私聊按 `getMe` numeric ID 进入独立的 group-safe 路径。静态配置中的群在启动时登记；Bot 新加入的未知群先进入 `pending`，所有者必须在私聊将其标成 `trusted` 或 `external` 后才会路由。随后应用模式：

| 模式 | 行为 |
|---|---|
| `adaptive` | 点名/回复立即响应；未定向 Owner 消息只交给配置的默认 Agent 判断 |
| `full` | 群内普通消息也可进入 Agent |
| `mentions` | 仅明确 @、回复 Bot 或命中别名时响应 |
| `muted` | 不调用 Agent |

多个 Bot 都可能收到同一条人类消息，所以 `/team` 等共享命令必须由统一桥认领一次。每个 Bot Token 仍保持自己的轮询器和 offset。

运行时群模式写入 SQLite，优先于静态 JSON；`/agent_pause` 是单 Agent 的群聊总闸，逐群暂停键是更窄的覆盖层。私聊保持可用，避免在群聊出错时把维护入口一起关掉。

群处理失败时，桥按 `bot + update + owner` 去重异常提醒，只把 Agent key、群标签和错误类别发到所有者私聊，不带原消息或异常正文。提醒按钮用随机 ID 回查服务端状态，可只暂停故障群。

## 3. 群聊身份不能只靠自然语言猜

给 Agent 的每条消息都带不可变元数据：

```json
{
  "sender": {
    "user_id": 123456,
    "username": "example",
    "display_name": "Example",
    "is_bot": false
  },
  "chat_id": -100123,
  "message_id": 88,
  "message_thread_id": 7,
  "reply_to": {
    "message_id": 84,
    "sender_user_id": 987654,
    "quoted_text": "……"
  }
}
```

原则：

- 人的稳定身份以 Telegram numeric user ID 为主键，不用昵称当主键。
- “你、他、她、楼上”先沿 reply edge 和最近发言者解析。
- 用户纠正身份后，旧的语义解释立即失效并重新解析，不能把错误摘要继续塞回上下文。
- 维护经过人工确认的人物表，但群聊只投影适合公开的部分。
- 出口增加硬检查：若回答无证据地把两个不同 ID 合并成同一人，阻止该答案并要求澄清。

## 4. Telegram 原生 bot-to-bot 与多 Agent 讨论

Bot API 10.0 已支持原生 bot-to-bot。私聊可用接收 Bot 的 `@username` 调用 `sendMessage`，发送方和接收方都要在 BotFather 开启 Bot-to-Bot Communication Mode。群内 command mention 或直接回复在至少一方开启该模式时可被接收；接收 Bot 开启该模式且为管理员或关闭 Group Privacy Mode 时，还可能收到未点名的 Bot 消息。

本桥只处理 Telegram 实际交付的 update，不复制消息来模拟另一个 Bot。接收后先用 `getMe` 返回的 numeric bot ID 核对发送者是否为配置内 peer，再执行路由：私聊 Bot 消息进入 group-safe runner；群聊 Bot 消息必须使用 `/command@TargetBot` 或直接回复当前 Bot。用户名只用于发送目标和显示，不是鉴权凭据。

所有者仍可选择 `/team` 运行确定性讨论轮次：

```text
主人发起 /team 2 话题
  → Agent A 生成
  → 桥把 A 的发言作为“被动上下文”交给 B
  → Agent B 生成
  → 桥把本轮内容交给 C
  → 第二轮……
```

`/team` 的中间发言是桥内被动上下文，不伪装成 Telegram update，也不能成为新的主人命令。无论原生 Bot 消息来自私聊还是群聊，每对已配置 Bot 都共享一个 SQLite 持久化滚动预算；默认 120 秒最多 4 次模型调用。预算在调用前扣除，失败、`NO_REPLY` 和低价值确认也计数，达到上限后静默停止。

每条新的人类群消息还会按 `chat + topic` 开启一个 causal epoch，同一条 Telegram 消息分发给多个 Bot 时只创建一次。一个 epoch 默认最多接受 8 次 Bot 模型调用；如果模型运行期间出现更新的人类消息，旧 epoch 的结果在发送前丢弃。`/flow_status` 是所有者只读查询，不会开启新 epoch。

普通群聊中，一个 Agent 真正发出的可见文本会写入其他配置内 Agent 的同群、同 Topic 滚动上下文。这个动作只写 SQLite，不调用其他 Agent，也不制造 Telegram update；因此其他 Agent 下次被人类正常唤醒时能看到刚才的发言，而不会形成自动互答链。

## 5. 并发与取消

- 长模型调用放在后台任务中，轮询循环继续处理 `/stop` 和状态查询。
- 可安全中断的 Agent：同一私聊新回合取消旧进程组，只保留最新回合。
- 依赖昂贵可恢复 session 的 Agent：同一私聊串行排队，避免破坏 session。
- 当前开源核心按 `agent + chat + thread` 串行处理群消息；高流量部署可在路由后增加短时间窗合批，但必须同时设置队列上限和失败熔断。
- typing task 在 `finally` 中停止，模型失败或取消都不会留下悬挂任务。

## 6. 上下文和记忆

上下文至少按 `agent + chat + thread` 隔离，并设消息数与字符数上限。每个 Agent 的长期记忆物理分库；私聊可读取经批准的私人资料，群聊只能读取明确标记为 group-safe 的投影。

不要让任何群成员通过自然语言覆盖系统配置、所有者身份或已确认的人物关系。普通群消息是对话内容，不是运维命令。

## 7. 文本交付

- 按 Telegram 文本长度限制安全分段，代码块不要截断在中间。
- 若不能保证 MarkdownV2 完整转义，使用纯文本；不要让一个星号导致整条发送失败。
- 每一段和每项媒体都保留 `reply_to_message_id` 与 `message_thread_id`。
- 不发送可见占位消息。后台每约 4 秒刷新一次 `sendChatAction(typing)`，最终文本只发送一次。
