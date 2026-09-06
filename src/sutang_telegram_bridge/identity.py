from __future__ import annotations

import json
import re
from typing import Any

from .models import IncomingMessage
from .store import DeliveryStore


def speaker(message: IncomingMessage) -> dict[str, Any]:
    return {
        "user_id": message.sender_id,
        "display_name": message.sender_name,
        "username": message.sender_username,
        "is_bot": message.sender_is_bot,
    }


def render_current(message: IncomingMessage) -> str:
    reply: dict[str, Any] | None = None
    if message.reply_to:
        author = message.reply_to.get("from") or {}
        reply = {
            "message_id": message.reply_to.get("message_id"),
            "sender_user_id": author.get("id"),
            "sender_username": author.get("username", ""),
            "sender_display_name": " ".join(
                value for value in (author.get("first_name", ""), author.get("last_name", "")) if value
            ),
            "quoted_text": message.reply_to.get("text") or message.reply_to.get("caption") or "",
        }
    envelope = {
        "sender": speaker(message),
        "chat_id": message.chat_id,
        "message_id": message.message_id,
        "message_thread_id": message.thread_id,
        "reply_to": reply,
        "text": message.text,
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2)


def identity_merge_conflict(store: DeliveryStore, chat_id: int, answer: str) -> bool:
    rows = store.participant_aliases(chat_id)
    aliases: list[tuple[str, int]] = []
    for row in rows:
        for value in (str(row["display_name"]), str(row["username"])):
            value = value.strip().lstrip("@").lower()
            if len(value) >= 2:
                aliases.append((value, int(row["user_id"])))
    lower = answer.lower()
    markers = r"(?:就是|等于|其实是|is\s+the\s+same\s+(?:person\s+)?as|=)"
    for left, left_id in aliases:
        for right, right_id in aliases:
            if left_id == right_id or left == right:
                continue
            pattern = re.escape(left) + r".{0,16}" + markers + r".{0,16}" + re.escape(right)
            reverse = re.escape(right) + r".{0,16}" + markers + r".{0,16}" + re.escape(left)
            if re.search(pattern, lower) or re.search(reverse, lower):
                return True
    return False
