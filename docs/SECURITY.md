# 安全与权限边界

## 威胁模型

桥同时面对四类风险：群成员的提示注入、恶意附件、模型生成的危险参数、主机上的权限横向移动。安全边界必须落在代码和操作系统里，不能只写一句“请勿执行危险操作”交给模型自觉。

## 必须执行的边界

- Token 只存在 root-owned `0600` 环境文件；不写源码、不打印、不进入 prompt。
- 桥使用独立 `sutang-bridge` 用户；每个 Agent 使用不同 Linux 用户。
- 桥只可 sudo 到固定用户并运行固定的 root-owned runner，不允许任意命令或 `SETENV`。
- runner 使用干净环境、固定 HOME、固定 CLI 参数和 cwd 白名单。
- Telegram 的 `user_id` / `chat_id` 做授权，昵称和群名只用于显示。
- 原生 bot-to-bot 只信任启动时通过 `getMe` 解析出的配置内 numeric bot ID；目标 username 只用于 Telegram 发送寻址。
- Bot 私聊使用 group-safe runner，不能读取所有者私聊工作目录、执行所有者命令或审批、处理附件、调用私人记忆写入；输入和输出的访问材料都会再次脱敏。
- Bot pair budget 在模型调用前以 SQLite 原子写入，按无方向 ID 对跨私聊/群聊计数，重启不会清零。
- 群聊 Bot 调用还受持久化 causal epoch 总预算约束；新的人类消息推进 epoch，旧 epoch 结果不能越过发送前检查。
- 跨 Agent 被动上下文只复制已经公开发送的同群同 Topic 文本，不复制私聊、附件、凭据或控制权限，也不会触发模型。
- 私聊、可信群、外部群分别定义工具、文件、记忆和媒体能力。
- 可恢复 provider session 仅按 Agent、群和 Topic 保存 opaque ID，并绑定信任状态
  与固定执行配置；私聊不复用，信任状态变化即轮换，session 本身不提升权限。
- 外部群默认禁止 shell、任意网络下载、私人仓库读取和跨聊天媒体复用。
- 附件下载有数量、单文件大小、展开项数与展开总体积上限。
- 所有输出媒体路径先 `resolve`，再验证位于 Agent 专属根目录。
- 日志只记录 update ID、chat 分类、阶段、耗时、重试次数和错误类别；不记录消息正文、prompt、模型输出或异常正文。

## systemd 加固原则

启用 `ProtectSystem=strict`、`PrivateTmp=true` 和窄化的 `ReadWritePaths`。如果桥必须通过 sudo 切换到 Agent 用户，`NoNewPrivileges` 与 `ProtectHome` 需根据该设计谨慎配置；这不是放弃隔离的理由，真正的控制点是固定 runner、sudoers 精确 allowlist 和 Agent 自身沙箱。

## 数据保留

- 完成的 update 尽快删除原始 Telegram payload，只保留幂等和交付所需元数据。
- SQLite 使用 WAL、文件权限 `0600`，备份同样加密或严格限权。
- 长期记忆按 Agent 分库，并保存 source、trust、chat、visibility 标签。
- 提供按 chat/user 删除记忆与媒体资产的管理入口。

## 审批边界

公开核心包含通用 Telegram 按钮审批：仅所有者私聊可创建，按钮回调按 Bot、聊天、随机审批 ID、选项和 numeric owner ID 校验；结果持久化、幂等，并以服务端认证的结构化上下文返回同一 Agent。普通聊天中的“可以”不会被当作按钮审批。

这层负责可靠取得选择，不会自动提升 Linux 权限，也不冒充 Codex、Claude 或其他 CLI 的原生工具审批。真正执行外部动作的适配器仍应校验审批 ID、动作参数和时效，并遵守自己的权限边界。

## 所有者控制边界

新群审批、Agent 开关和异常暂停按钮只接受配置中的 numeric owner ID，并同时校验 Bot、私聊和服务端保存的随机 ID。callback payload 不携带 Token、消息正文、错误正文或待执行命令。异常提醒也不复制原消息；死信列表只展示 update ID 与错误类别。

## 绝不能公开的内容

Bot Token、OAuth/API 凭据、Cookie、SSH 私钥、真实 owner/group ID、私人聊天导出、私人记忆文件、生产环境的完整绝对路径映射。
