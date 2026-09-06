"""Harmless adapter used only to verify the Telegram transport."""

import json
import sys

name = sys.argv[1] if len(sys.argv) > 1 else "Echo Agent"
prompt = sys.stdin.read()
marker = "Current immutable Telegram envelope:\n"
text = ""
if marker in prompt:
    fragment = prompt.split(marker, 1)[1]
    try:
        text = str(json.JSONDecoder().raw_decode(fragment.lstrip())[0].get("text", ""))
    except (ValueError, TypeError, AttributeError):
        pass
print(f"{name} 已收到：{text or '[附件消息]'}")
