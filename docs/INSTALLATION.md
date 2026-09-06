# 安装与配置

以下是可移植的部署骨架。路径和 Agent 数量可以改，但权限边界不要省。

## 1. 创建账号与目录

```bash
sudo useradd --system --home /var/lib/sutang-telegram-bridge --shell /usr/sbin/nologin sutang-bridge
sudo useradd --create-home agent-a
sudo useradd --create-home agent-b
sudo useradd --create-home agent-c
sudo groupadd --force sutang-agent-files
sudo usermod -aG sutang-agent-files sutang-bridge
sudo usermod -aG sutang-agent-files agent-a
sudo usermod -aG sutang-agent-files agent-b
sudo usermod -aG sutang-agent-files agent-c
sudo install -d -m 0700 -o root -g root /etc/sutang-telegram-bridge
sudo install -d -m 0711 -o sutang-bridge -g sutang-bridge /var/lib/sutang-telegram-bridge
sudo install -d -m 0755 -o root -g root /opt/sutang-telegram-bridge /usr/local/libexec/sutang-telegram-bridge
```

每个 Agent 的 CLI 登录和私有仓库归对应 Linux 用户所有。桥账号不要加入这些用户的组。

示例使用单独的 `sutang-agent-files` 组只交接收到的附件；它不授予任何 Agent home 或仓库权限。若需要更严格隔离，可给每个 Agent 建独立附件组，并在配置中分别设置 `attachment_group`。

## 2. Telegram 设置

为每个 Agent 创建一个 Bot，保存 Token。需要 Bot 互相通信时，为参与者开启 BotFather 的 Bot-to-Bot Communication Mode：原生私聊要求双方都开启；群内 command mention 或直接回复要求至少一方开启。若接收 Bot 还要看见未点名的 Bot 群消息，它必须是群管理员或关闭 Group Privacy Mode。本桥为防广播循环，仍只唤醒被原生点名或直接回复的 Bot。按 BotFather 提示在设置变更后重新加入群。

取得所有者 numeric user ID、允许群 ID 和可信群 ID。不要用 `@username` 做权限判断。

如需语音识别，安装桥后运行：

```bash
sudo ./scripts/install-voice.sh
```

它安装固定版本的本地 faster-whisper、下载固定 revision 的 small 模型、更新配置并在服务已运行时重启。语音不上传云端，也不需要 API Key。

## 3. 环境文件

复制 [环境变量示例](../examples/bridge.env.example) 到：

```text
/etc/sutang-telegram-bridge/bridge.env
```

然后：

```bash
sudo chown root:root /etc/sutang-telegram-bridge/bridge.env
sudo chmod 0600 /etc/sutang-telegram-bridge/bridge.env
```

环境文件不得进入 Git、日志或 Agent prompt。

## 4. 固定 runner

每个 runner 都是 root-owned 可执行文件，职责只有：清理环境、设置正确 HOME、检查 cwd 白名单、以固定参数调用对应 CLI。桥使用类似下面的 argv：

```text
sudo -n -u agent-a /usr/local/libexec/sutang-telegram-bridge/run-agent-a
```

提示词从 stdin 传入。禁止 `shell=True`，禁止让模型决定用户名、runner 路径或 cwd。sudoers 只放行精确的固定 runner，并先运行 `visudo -cf` 验证。

## 5. systemd

仓库已经提供短安装脚本：

```bash
sudo ./scripts/install.sh
```

它安装源码、示例配置和 systemd unit，但不会猜测你的 Agent CLI。按 [Agent wrapper 接口](AGENT-ADAPTERS.md) 安装三个固定 runner，填写配置后再执行：

```bash
sudo systemctl enable --now sutang-telegram-bridge.service
sudo systemctl status sutang-telegram-bridge.service
```

部署新版本前先备份 SQLite 和配置，停止旧 poller，再替换代码；启动后运行验收，不要用未经检查的一行远程脚本覆盖生产目录。

## 6. 必做验收

1. 非所有者人类和未配置 Bot 的私聊不能触发任何 Agent；配置内 Bot 只能进入 group-safe 路径。
2. 未授权群不能触发；授权群四种模式分别符合预期。
3. 群友回复另一位群友时不会被识别成主人。
4. 处理较慢时只显示 typing，没有可见占位消息。
5. `/stop` 能在模型运行中生效。
6. 服务在“生成后、发送前”强制退出，重启后只发送缓存回复，不再次调用模型。
7. ZIP 路径穿越、symlink 和压缩炸弹样本都被拒绝。
8. 私聊登记的贴纸不能被另一个群复用；同群同 Bot 可以复用。
9. Topic 内回复仍落在原 Topic。
10. 日志搜索不到 Token、完整 prompt 和完整聊天正文。
11. 配置内 Bot 可通过 `send_bot_text("@TargetExampleBot", text)` 发起原生私聊；未知或仅用户名相同的 Bot 不能触发 Agent。
12. 同一 Bot 对快速往返在达到 `bot_pair_call_limit` 后静默停止，重启服务也不会提前清空滚动窗口。
13. 在一次 Bot 调用尚未完成时发送新的人类群消息，旧结果不得发送；`/flow_status` 应显示新的 epoch。一个 Agent 的可见群回复应进入其他 Agent 的被动上下文，但不能自行唤醒它们。
