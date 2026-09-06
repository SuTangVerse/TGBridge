# 所有者控制台、新群审批与故障恢复

以下控制只在配置中的 owner 私聊生效；群成员、转发消息和伪造昵称都不能取得权限。按钮 callback 使用随机短 ID，实际目标保存在 SQLite，不把消息正文、异常正文、Token 或命令塞进按钮。

## Agent 与群开关

在某个 Agent 的私聊发送 `/agent_switch`，会得到一个 Inline Keyboard：第一行暂停或恢复该 Agent 的全部群聊，后续各行控制单个群。所有开关只影响群聊，维护私聊始终保留。

也可使用文本命令：

```text
/agent_pause
/agent_resume
/agent_pause_group -1001234567890
/agent_resume_group -1001234567890
```

群内的 `/agent_on`、`/agent_off`、`/agent_mute` 和 `/agent_mode` 控制当前群的路由强度；它们与暂停开关是两层状态，任一层禁止都会停止群响应。

## 新群审批

Bot 收到有效的 `my_chat_member` 入群更新时，会登记群并向 owner 私聊发送审批卡。选择：

- 可信群：默认模式为 `adaptive`，可按可信附件/媒体规则工作。
- 外部群：默认模式为 `mentions`，仅在 @、Reply 或别名点名时响应，使用更窄的能力边界。

审批前状态为 `pending`，桥不会把群消息交给 Agent。没看到卡片时，在该 Bot 私聊发送 `/pending_groups`；`/groups` 可查看已登记群和当前信任状态。

## 异常提醒与一键暂停

群消息处理失败时，桥向 owner 私聊发送去重提醒，只包含 Agent key、群标签和异常类型，例如 `TimeoutError`。提醒不复制原消息、prompt、模型输出或异常详情。点击“暂停该群”只会暂停该 Agent 在故障群的响应，不影响私聊和其他群。

## 死信查看与重试

在 Agent 私聊发送 `/delivery`，可查看 `received / processing / generated / dead` 数量，以及该 Bot 最近的死信 update ID 和错误类别。修复根因后执行：

```text
/retry_update 123456789
```

只有仍保留原始 payload 的 `dead` 更新可以重试。重试会清零尝试次数并重新入队；它不会绕过 owner 鉴权，也不会跨 Bot 操作死信。原始 payload 在完成后立即清除，过期死信也会按保留策略清除。
