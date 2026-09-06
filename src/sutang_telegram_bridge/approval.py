from __future__ import annotations

import json
import re
from dataclasses import dataclass


APPROVAL_RE = re.compile(r"<telegram_approval>(.*?)</telegram_approval>", re.DOTALL)
OPTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


@dataclass(frozen=True)
class ApprovalOption:
    id: str
    label: str


@dataclass(frozen=True)
class ApprovalRequest:
    title: str
    detail: str
    options: tuple[ApprovalOption, ...]


def extract_approval_control(text: str) -> tuple[str, ApprovalRequest | None]:
    matches = APPROVAL_RE.findall(text)
    if not matches:
        return text.strip(), None
    if len(matches) != 1:
        raise ValueError("exactly one telegram_approval block is allowed")
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise ValueError("telegram_approval block is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("telegram_approval must be an object")
    title = str(payload.get("title", "")).strip()
    detail = str(payload.get("detail", "")).strip()
    raw_options = payload.get("options")
    if not title or len(title) > 120 or len(detail) > 2000:
        raise ValueError("approval title/detail is missing or too long")
    if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 4:
        raise ValueError("approval options must contain two to four items")
    options: list[ApprovalOption] = []
    seen: set[str] = set()
    for item in raw_options:
        if not isinstance(item, dict):
            raise ValueError("approval option must be an object")
        option_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        if not OPTION_ID_RE.fullmatch(option_id) or not label or len(label) > 32:
            raise ValueError("approval option id or label is invalid")
        if option_id in seen:
            raise ValueError("approval option ids must be unique")
        seen.add(option_id)
        options.append(ApprovalOption(option_id, label))
    return APPROVAL_RE.sub("", text).strip(), ApprovalRequest(
        title=title,
        detail=detail,
        options=tuple(options),
    )


def approval_markup(approval_id: str, options: tuple[ApprovalOption, ...]) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": option.label,
                    "callback_data": f"ap:{approval_id}:{option.id}",
                }
                for option in options
            ]
        ]
    }
