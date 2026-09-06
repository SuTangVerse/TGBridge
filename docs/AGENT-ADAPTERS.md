# Agent wrapper 接口

桥不绑定 Codex、Claude、Grok 或其他厂商。每个 Agent 只需满足一个小接口：

```text
stdin  ← 完整提示词与 Telegram 结构化上下文
stdout → 仅最终用户可见答案，可选一个 telegram_media 控制块
exit 0 → 成功
其他退出码 → 失败，stderr 仅用于短错误摘要
```

配置中的 `command` 必须是 argv 数组，第一个元素必须为绝对路径。桥使用 `create_subprocess_exec`，不会执行 shell 拼接。生产环境推荐让 command 指向 `/usr/bin/sudo -n -u <agent-user> <fixed-runner>`；sudoers 只放行 root-owned 固定 runner。

## wrapper 要做的事

1. 使用 `env -i` 清除桥的 Token 和环境变量。
2. 设置该 Agent 自己的 HOME、PATH 和必要的非秘密选项。
3. 固定工作目录白名单；不接受 prompt 提供 cwd。
4. 调用 CLI 的非交互模式，从 stdin 读取输入。
5. 只把最终答案写到 stdout；进度、调试和工具日志写 stderr。

可从 [wrapper 示例](../examples/run-agent-wrapper.sh) 复制。不同 CLI 的参数变化较快，应以各自官方文档为准。

## 附件权限

桥下载的附件默认权限为 `0600`。若配置了 `attachment_group`，下载完成后会把本回合目录设为组可遍历、文件设为 `0640`。`sutang-bridge` 和对应 Agent 必须都是该组成员；不要把附件改成 world-readable。

## 媒体输出

wrapper 不直接调用 Telegram。Agent 在最终答案末尾输出 `<telegram_media>` 控制块，由桥检查 asset scope 和真实路径后发送。模型提交的任意 `file_id` 不会被接受。

## Reaction 输出

Agent 可以输出 `<telegram_reaction>{"emoji":"❤️"}</telegram_reaction>`。如果只需轻量确认，可输出 `NO_REPLY`，由桥按 `silent_reaction` 配置决定是否添加默认 Reaction。
