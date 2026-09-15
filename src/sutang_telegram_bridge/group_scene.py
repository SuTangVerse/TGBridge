from __future__ import annotations

import json
import re
from dataclasses import dataclass


SCENE_REQUEST_RE = re.compile(
    r"<telegram_group_scene_request>(.*?)</telegram_group_scene_request>",
    re.DOTALL,
)
SCENE_OPEN_RE = re.compile(r"<telegram_group_scene_request>.*", re.DOTALL)
SCENE_CLOSE_RE = re.compile(r"</telegram_group_scene_request>")


@dataclass(frozen=True)
class GroupSceneSignal:
    summary: str


def extract_group_scene_signal(text: str) -> tuple[str, GroupSceneSignal | None]:
    matches = SCENE_REQUEST_RE.findall(str(text))
    if not matches:
        return str(text).strip(), None
    visible = SCENE_REQUEST_RE.sub("", str(text)).strip()
    if len(matches) != 1:
        raise ValueError("exactly one group scene request block is allowed")
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ValueError("group scene request block is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("group scene request must be an object")
    summary = " ".join(str(payload.get("summary", "")).split())
    if not summary or len(summary) > 240:
        raise ValueError("group scene request summary is missing or too long")
    return visible, GroupSceneSignal(summary=summary)


def strip_group_scene_signal(text: str) -> str:
    stripped = SCENE_REQUEST_RE.sub("", str(text))
    stripped = SCENE_OPEN_RE.sub("", stripped)
    return SCENE_CLOSE_RE.sub("", stripped).strip()
