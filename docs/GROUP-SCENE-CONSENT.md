# 群聊临时私密场景

这个可选功能适合“Agent 平时在群里保持克制，但 Owner 明确要求在当前群公开展开一段私密、亲密或敏感角色互动”的情况。它是群聊输出方式的临时同意，不是记忆、文件、工具或外部动作授权。

## 开启

只为需要此功能的 Agent 加配置：

```json
{
  "group_scene_request_ttl_seconds": 300,
  "group_scene_active_ttl_seconds": 900,
  "agents": [
    {
      "key": "agent-a",
      "group_scene_consent": true
    }
  ]
}
```

默认关闭。请求确认默认 5 分钟过期，场景默认 15 分钟过期；前者可设 30–1800 秒，后者可设 60–86400 秒。

## 使用流程

1. 只有配置中的 numeric Owner ID 能在可信群发起。
2. Agent 可以从自然语言判断这是公开私密场景，并输出隐藏的严格 JSON 控制块；也可由 Owner 使用 `/scene_open <request>` 确定性发起。
3. 桥不会先在群里执行，而是把群、Topic、脱敏原话和允许/拒绝按钮发到同一个 Bot 的 Owner 私聊。
4. Owner 点击允许后，桥只把已保存的原消息回放到原群、原 Topic，并在提示词中加入服务端验证的限时场景边界。
5. 后续仅同一个 Owner 在同一 Agent、群和 Topic 的消息能继承场景；其他成员、其他 Topic、其他群和其他 Agent 都不能继承。
6. Owner 可点私聊里的关闭按钮，或在原 Topic 发送 `/scene_close`。关闭和过期都会清除该 Agent 在该 Topic 的有界上下文及增量 provider session；已经发到 Telegram 的消息无法撤回。

自然语言触发使用的隐藏块为：

```text
<telegram_group_scene_request>{"summary":"brief neutral description"}</telegram_group_scene_request>
```

桥只在“可信群 + 已开启功能的 Agent + 当前发送者是已验证 Owner + 尚无活动场景”时接受它。控制块永不直接发到 Telegram。若模型误判，Owner 不点允许即可，不会公开展开。

## 不授予什么

- 不把群 runner 改成私聊 runner，不提升 Linux 用户、cwd、附件或工具权限。
- 不接入或开放私人记忆；若部署方另有记忆网关，仍须单独实现逐条、逐回合的披露授权。
- 不允许凭据、Token、密码、私钥或私密 URL 借此越过原有边界。
- 不让群里的普通成员替 Owner 发起、确认或继承场景。

这一状态持久化在 bridge 的 mode-0600 SQLite 数据库中。随机 scene ID 不携带正文，按钮同时核对 Bot 和 numeric Owner ID；允许、拒绝、过期、关闭均为原子状态转换。功能关闭或群不再可信时，活动场景会失败关闭并清理运行时上下文。
