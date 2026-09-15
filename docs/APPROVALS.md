# Telegram 审批按钮

当 Agent 在所有者私聊中需要明确选择时，可以在可见回答末尾附加：

```text
<telegram_approval>{"title":"发布消息？","detail":"确认后会产生外部可见操作","options":[{"id":"approve","label":"批准"},{"id":"reject","label":"拒绝"}]}</telegram_approval>
```

桥会删除控制块，另发一张带 Inline Keyboard 的审批卡。按钮只接受配置中的 numeric owner ID；请求绑定发起 Bot 和私聊，随机 ID 不携带动作正文。选择以 SQLite 事务记录，同一个 Telegram update 可安全重放，其他点击只会得到“已经处理”。按钮默认 24 小时过期。

确认后，桥把 `approval_id`、问题、选项 ID 和标签作为“服务端已验证审批”交回原 Agent，再发送其后续回答。群聊和第三方消息不能创建审批卡。

## 接入真实动作

按钮证明的是“谁选择了哪个选项”，不是无限授权。Agent wrapper 或动作服务应把待执行动作及参数保存在服务端，按审批 ID 找回并核对，避免把聊天文字、按钮标签或模型再次生成的参数直接当作命令。高风险动作还应设置更短的有效期和专用 allowlist。

群聊里需要先私下确认、再回原群生效的临时场景使用另一套独立状态机，见
[群聊临时私密场景](GROUP-SCENE-CONSENT.md)。普通审批不会打开群场景，群场景按钮也不会取得动作权限。
