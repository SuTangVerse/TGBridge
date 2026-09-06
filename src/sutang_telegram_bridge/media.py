from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import AgentConfig
from .store import DeliveryStore

MEDIA_RE = re.compile(r"<telegram_media>(.*?)</telegram_media>", re.DOTALL)
REACTION_RE = re.compile(r"<telegram_reaction>(.*?)</telegram_reaction>", re.DOTALL)
KINDS = {"photo", "animation", "sticker"}


def extract_media_control(text: str) -> tuple[str, list[dict[str, Any]]]:
    matches = MEDIA_RE.findall(text)
    if not matches:
        return text.strip(), []
    if len(matches) != 1:
        raise ValueError("exactly one telegram_media block is allowed")
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ValueError("telegram_media block is not valid JSON") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) > 4:
        raise ValueError("telegram_media.items must be an array of at most four items")
    clean = MEDIA_RE.sub("", text).strip()
    return clean, items


def extract_reaction_control(text: str) -> tuple[str, str | None]:
    matches = REACTION_RE.findall(text)
    if not matches:
        return text.strip(), None
    if len(matches) != 1:
        raise ValueError("exactly one telegram_reaction block is allowed")
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ValueError("telegram_reaction block is not valid JSON") from exc
    emoji = str(payload.get("emoji", "")) if isinstance(payload, dict) else ""
    if not emoji or len(emoji) > 16 or any(ord(char) < 32 for char in emoji):
        raise ValueError("telegram reaction emoji is invalid")
    return REACTION_RE.sub("", text).strip(), emoji


def _local_source(agent: AgentConfig, raw_path: str) -> str:
    if agent.media_root is None:
        raise ValueError("this agent has no local media root")
    root = agent.media_root.resolve()
    candidate = Path(raw_path)
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("media path is outside the agent media root or is not a file")
    return str(candidate)


def validate_media_items(
    items: list[dict[str, Any]],
    agent: AgentConfig,
    store: DeliveryStore,
    bot_key: str,
    chat_id: int,
    allow_local: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or str(item.get("kind")) not in KINDS:
            raise ValueError("media item has an unsupported kind")
        kind = str(item["kind"])
        caption = str(item.get("caption", ""))[:1024]
        asset_id = item.get("asset_id")
        path = item.get("path")
        if bool(asset_id) == bool(path):
            raise ValueError("media item must contain exactly one of asset_id or path")
        if asset_id:
            source = store.resolve_asset(bot_key, chat_id, str(asset_id), kind)
            if source is None:
                raise ValueError("media asset is unknown in this bot and chat")
            result.append({"kind": kind, "source": source, "caption": caption, "local": False})
        else:
            if not allow_local:
                raise ValueError("local media paths are disabled for this chat")
            source = _local_source(agent, str(path))
            result.append({"kind": kind, "source": source, "caption": caption, "local": True})
    return result


def split_text(text: str, limit: int = 4000) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks
