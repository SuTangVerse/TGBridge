from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .models import BotIdentity, IncomingMessage
from .privacy import redact_access_material

BOT_USERNAME_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, timeout: float = 40.0):
        self._token = token
        self._base = f"https://api.telegram.org/bot{token}/"
        self._file_base = f"https://api.telegram.org/file/bot{token}/"
        self._timeout = timeout

    def _sync_request(
        self, method: str, payload: dict[str, Any] | None = None, file: Path | None = None
    ) -> Any:
        payload = {k: v for k, v in (payload or {}).items() if v is not None}
        if file is None:
            body = urllib.parse.urlencode(payload).encode()
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
        else:
            boundary = "----sutang" + uuid.uuid4().hex
            chunks: list[bytes] = []
            for key, value in payload.items():
                chunks.extend(
                    [
                        f"--{boundary}\r\n".encode(),
                        f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                        str(value).encode("utf-8"),
                        b"\r\n",
                    ]
                )
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="media"; filename="{file.name}"\r\n'.encode(),
                    f"Content-Type: {mime}\r\n\r\n".encode(),
                    file.read_bytes(),
                    b"\r\n",
                    f"--{boundary}--\r\n".encode(),
                ]
            )
            body = b"".join(chunks)
            headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        request = urllib.request.Request(self._base + method, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TelegramError(f"Telegram {method} request failed: {type(exc).__name__}") from exc
        if not data.get("ok"):
            raise TelegramError(f"Telegram {method} rejected the request: {data.get('description', 'unknown error')}")
        return data.get("result")

    async def request(
        self, method: str, payload: dict[str, Any] | None = None, file: Path | None = None
    ) -> Any:
        return await asyncio.to_thread(self._sync_request, method, payload, file)

    async def get_me(self) -> BotIdentity:
        result = await self.request("getMe")
        return BotIdentity(id=int(result["id"]), username=str(result.get("username", "")))

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload = {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": json.dumps(["message", "callback_query", "my_chat_member"]),
        }
        result = await self.request("getUpdates", payload)
        return list(result or [])

    async def send_action(self, chat_id: int, thread_id: int | None) -> None:
        await self.request(
            "sendChatAction",
            {"chat_id": chat_id, "message_thread_id": thread_id, "action": "typing"},
        )

    async def set_reaction(self, chat_id: int, message_id: int, emoji: str) -> None:
        await self.request(
            "setMessageReaction",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": json.dumps([{"type": "emoji", "emoji": emoji}]),
                "is_big": False,
            },
        )

    @staticmethod
    def _reply_fields(thread_id: int | None, reply_to: int | None) -> dict[str, Any]:
        fields: dict[str, Any] = {"message_thread_id": thread_id}
        if reply_to is not None:
            fields["reply_parameters"] = json.dumps(
                {"message_id": reply_to, "allow_sending_without_reply": True}
            )
        return fields

    async def send_text(
        self,
        chat_id: int,
        text: str,
        thread_id: int | None,
        reply_to: int | None,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload = {"chat_id": chat_id, "text": text}
        payload.update(self._reply_fields(thread_id, reply_to))
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        await self.request("sendMessage", payload)

    async def send_bot_text(self, username: str, text: str) -> None:
        """Start a Telegram-native private bot chat by public username."""
        target = str(username).strip()
        if not target.startswith("@"):
            target = "@" + target
        if not BOT_USERNAME_RE.fullmatch(target):
            raise ValueError("invalid Telegram bot username")
        if not str(text).strip():
            raise ValueError("bot-to-bot text must not be empty")
        await self.request(
            "sendMessage",
            {"chat_id": target, "text": redact_access_material(str(text))},
        )

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        await self.request(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text[:180]},
        )

    async def clear_reply_markup(self, chat_id: int, message_id: int) -> None:
        await self.request(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": "{}"},
        )

    async def send_media(
        self,
        kind: str,
        chat_id: int,
        source: str,
        caption: str,
        thread_id: int | None,
        reply_to: int | None,
        local: bool,
    ) -> None:
        methods = {"photo": "sendPhoto", "animation": "sendAnimation", "sticker": "sendSticker"}
        fields = {"photo": "photo", "animation": "animation", "sticker": "sticker"}
        payload: dict[str, Any] = {"chat_id": chat_id}
        payload.update(self._reply_fields(thread_id, reply_to))
        if caption and kind != "sticker":
            payload["caption"] = caption[:1024]
        if local:
            payload[fields[kind]] = "attach://media"
            await self.request(methods[kind], payload, Path(source))
        else:
            payload[fields[kind]] = source
            await self.request(methods[kind], payload)

    async def download(self, file_id: str, destination: Path, max_bytes: int) -> None:
        result = await self.request("getFile", {"file_id": file_id})
        file_path = str(result["file_path"])
        url = self._file_base + file_path

        def _download() -> None:
            request = urllib.request.Request(url)
            total = 0
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response, destination.open("wb") as out:
                    while chunk := response.read(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise TelegramError("attachment exceeds configured size limit")
                        out.write(chunk)
                os.chmod(destination, 0o600)
            except Exception:
                destination.unlink(missing_ok=True)
                raise

        await asyncio.to_thread(_download)


def parse_update(bot_key: str, update: dict[str, Any]) -> IncomingMessage | None:
    membership = update.get("my_chat_member")
    if isinstance(membership, dict):
        chat = membership.get("chat")
        sender = membership.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return None
        first = str(sender.get("first_name", "")).strip()
        last = str(sender.get("last_name", "")).strip()
        display = " ".join(part for part in (first, last) if part) or str(
            sender.get("username", "unknown")
        )
        return IncomingMessage(
            bot_key=bot_key,
            update_id=int(update["update_id"]),
            chat_id=int(chat["id"]),
            chat_type=str(chat.get("type", "unknown")),
            message_id=0,
            thread_id=None,
            sender_id=int(sender.get("id", 0)),
            sender_name=display,
            sender_username=str(sender.get("username", "")),
            sender_is_bot=bool(sender.get("is_bot", False)),
            text="[Bot membership changed]",
            reply_to=None,
            raw_message=membership,
            event_type="my_chat_member",
            chat_title=str(chat.get("title", "")),
        )
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message")
        sender = callback.get("from")
        if not isinstance(message, dict) or not isinstance(sender, dict):
            return None
        chat = message.get("chat")
        if not isinstance(chat, dict) or not callback.get("id"):
            return None
        first = str(sender.get("first_name", "")).strip()
        last = str(sender.get("last_name", "")).strip()
        display = " ".join(part for part in (first, last) if part) or str(sender.get("username", "unknown"))
        return IncomingMessage(
            bot_key=bot_key,
            update_id=int(update["update_id"]),
            chat_id=int(chat["id"]),
            chat_type=str(chat.get("type", "unknown")),
            message_id=int(message.get("message_id", 0)),
            thread_id=int(message["message_thread_id"]) if message.get("message_thread_id") else None,
            sender_id=int(sender.get("id", 0)),
            sender_name=display,
            sender_username=str(sender.get("username", "")),
            sender_is_bot=bool(sender.get("is_bot", False)),
            text="[Owner selected an approval button]",
            reply_to=None,
            raw_message=message,
            event_type="callback_query",
            callback_query_id=str(callback["id"]),
            callback_data=str(callback.get("data", "")),
            chat_title=str(chat.get("title", "")),
        )
    message = update.get("message")
    if not isinstance(message, dict) or "from" not in message or "chat" not in message:
        return None
    sender = message["from"]
    chat = message["chat"]
    first = str(sender.get("first_name", "")).strip()
    last = str(sender.get("last_name", "")).strip()
    display = " ".join(part for part in (first, last) if part) or str(sender.get("username", "unknown"))
    reply = message.get("reply_to_message")
    return IncomingMessage(
        bot_key=bot_key,
        update_id=int(update["update_id"]),
        chat_id=int(chat["id"]),
        chat_type=str(chat.get("type", "unknown")),
        message_id=int(message["message_id"]),
        thread_id=int(message["message_thread_id"]) if message.get("message_thread_id") else None,
        sender_id=int(sender["id"]),
        sender_name=display,
        sender_username=str(sender.get("username", "")),
        sender_is_bot=bool(sender.get("is_bot", False)),
        text=str(message.get("text") or message.get("caption") or ""),
        reply_to=reply if isinstance(reply, dict) else None,
        raw_message=message,
        chat_title=str(chat.get("title", "")),
    )
