# 图片、GIF、贴纸、文档与压缩包

## 接收侧

统一解析以下 Telegram 类型：

- `photo`
- `document`
- `animation`
- `sticker`
- `voice`
- `audio`

建议默认限制：每条消息最多 8 个文件，每文件最多 20 MiB。附件使用安全化文件名保存到独立消息目录，并把路径、MIME、原文件名和来源作为结构化 manifest 交给 Agent。

权限分层：

| 场景 | 推荐能力 |
|---|---|
| 所有者私聊 | 接收附件；按 Agent 私聊 profile 读取 |
| 可信群 | 被点名/回复时接收；只读本次附件 |
| 外部群 | 未点名的第三方附件不交给 Agent；禁止访问私人媒体库 |

若某个 Agent 的沙箱无法读取桥的附件目录，可把本次精确文件复制到短期镜像目录，仅开放 `Read/Grep`，任务结束后清理。不要为了一个附件给整个群聊开放 home 或 shell。

## 压缩包

ZIP 与 TAR 家族自动展开前必须逐项校验：

- 拒绝绝对路径、`..` 路径穿越和逃出目标目录的规范化路径。
- 拒绝 symlink、hardlink、device、FIFO 等非普通文件/目录。
- 先统计再展开；建议最多 256 项、总展开体积最多 100 MiB。
- 超限或损坏时保留原包并返回清楚错误，不部分静默展开。
- RAR/7z 默认不自动解压，只作为不透明文档传递。

## 发送侧

让 Agent 输出一个不会展示给用户的控制块，桥剥离、验证后调用 Telegram：

```xml
<telegram_media>{"items":[
  {"kind":"sticker","asset_id":"tg_abcd1234"},
  {"kind":"animation","path":"reactions/happy.gif","caption":"给你"},
  {"kind":"photo","path":"cards/hello.png","caption":""}
]}</telegram_media>
```

规则：

- 单次最多 4 项，只接受 `photo / animation / sticker`。
- `path` 规范化后必须位于当前 Agent 的 `.telegram-media` 根目录内。
- 模型不能直接提交 Telegram `file_id`；桥把收到的素材登记成不透明 `asset_id`。
- `asset_id` 绑定 `bot_key + chat_id`，其他 Bot、其他群或其他私聊不能复用。
- 外部群只允许同聊天 `asset_id`；本地媒体路径仅在所有者私聊和可信群开放。
- 控制块被剥离后允许正文为空，即可只发贴纸/GIF/图片。
- 媒体也进入 outbox，崩溃恢复时复用已缓存项目，不能重新调用模型。
- 是否主动发贴纸、GIF 或图片由 Agent 根据当下语境决定，不按条数或频率配额机械发送。
- 群聊必须先通过既有的 @、Reply、唤醒与注意力判断；发送能力不会自行唤醒 Agent。

## Reaction

Agent 可在最终答案中追加：

```xml
<telegram_reaction>{"emoji":"👀"}</telegram_reaction>
```

桥剥离控制块后调用 `setMessageReaction`。Agent 可按语境自主选择 Telegram 标准 Reaction，并可将它与文字/媒体一起发送或单独使用；同样不设机械频率。Reaction 只绑定当前源消息，模型不能指定任意消息 ID。Reaction 也进入持久交付操作。配置 `silent_reaction` 后，Agent 没有自行选择且输出 `NO_REPLY` 时，可以使用默认 Reaction 兜底。

## 语音识别

桥会下载 `voice` 和 `audio`，再将文件路径作为最后一个 argv 参数交给配置的固定转写命令。转写器必须把纯文本写到 stdout：

```json
{
  "transcription": {
    "command": ["/usr/local/libexec/sutang-telegram-bridge/transcribe-voice"],
    "timeout_seconds": 120,
    "max_chars": 12000,
    "pass_env": []
  }
}
```

仓库自带可运行的本地 faster-whisper 后端；安装桥后执行 `sudo ./scripts/install-voice.sh` 即可启用。也可以把 wrapper 换成 whisper.cpp 或自己的受控服务。桥不执行 shell 字符串，也不会把 Telegram Bot Token 传给转写器。转写文本明确标记为不可信用户内容；失败时保留原音频附件，不编造识别结果。

## 怎么给 Agent 一张 GIF 或贴纸

最省事的方法：把素材直接发到“需要使用它的那个 Bot 所在的同一个聊天”。例如希望 Agent A 在某群复用，就在该群发给 Agent A；在私聊登记的资产默认不能跨到群里。

另一种方法是在服务器预置审核过的媒体库：

```text
/home/agent-a/shared/.telegram-media/
├── reactions/
│   ├── happy.gif
│   └── nope.webp
└── cards/
    └── hello.png
```

目录由对应 Agent 用户拥有，桥只接受此根目录下的规范化路径。不要把下载目录、`/tmp` 或整个 home 加入允许列表。

## 发送 API 对应关系

- 图片：`sendPhoto`
- GIF 或无声/动画 MP4：`sendAnimation`
- Telegram 贴纸：`sendSticker`
- Reaction：`setMessageReaction`

字段和当前限制以 [Telegram Bot API](https://core.telegram.org/bots/api) 为准。
