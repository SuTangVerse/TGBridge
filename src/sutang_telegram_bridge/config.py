from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AgentConfig, BridgeConfig, TranscriptionConfig

GROUP_MODES = {"adaptive", "full", "mentions", "muted"}


def _ids(value: Any, name: str) -> frozenset[int]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array of numeric Telegram IDs")
    try:
        return frozenset(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} contains a non-numeric ID") from exc


def _path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value)).expanduser().resolve()


def _positive_int(data: dict[str, Any], key: str, default: int) -> int:
    value = int(data.get(key, default))
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def load_config(path: str | Path) -> tuple[BridgeConfig, dict[str, str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config root must be a JSON object")

    agents: list[AgentConfig] = []
    tokens: dict[str, str] = {}
    seen: set[str] = set()
    for item in raw.get("agents", []):
        if not isinstance(item, dict):
            raise ValueError("each agent must be a JSON object")
        key = str(item.get("key", "")).strip()
        if not key or key in seen:
            raise ValueError("agent keys must be non-empty and unique")
        seen.add(key)
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ValueError(f"agent {key}: command must be a non-empty argv array")
        if not Path(command[0]).is_absolute():
            raise ValueError(f"agent {key}: command[0] must be an absolute path")
        incremental_group_sessions = item.get(
            "incremental_group_sessions", False
        )
        if type(incremental_group_sessions) is not bool:
            raise ValueError(
                f"agent {key}: incremental_group_sessions must be boolean"
            )
        token_env = str(item.get("token_env", "")).strip()
        token = os.environ.get(token_env, "")
        if not token:
            raise ValueError(f"agent {key}: environment variable {token_env!r} is empty")
        tokens[key] = token
        agents.append(
            AgentConfig(
                key=key,
                token_env=token_env,
                command=tuple(command),
                aliases=tuple(str(v) for v in item.get("aliases", [])),
                private_cwd=_path(item.get("private_cwd")),
                group_cwd=_path(item.get("group_cwd")),
                media_root=_path(item.get("media_root")),
                attachment_group=str(item["attachment_group"]) if item.get("attachment_group") else None,
                pass_env=tuple(str(v) for v in item.get("pass_env", [])),
                incremental_group_sessions=incremental_group_sessions,
            )
        )
    if not agents:
        raise ValueError("at least one agent is required")
    token_env_names = {agent.token_env for agent in agents}
    for agent in agents:
        leaked = token_env_names.intersection(agent.pass_env)
        if leaked:
            raise ValueError(f"agent {agent.key}: pass_env must not include Telegram token variables")

    owner_ids = _ids(raw.get("owner_ids", []), "owner_ids")
    if not owner_ids:
        raise ValueError("owner_ids must not be empty")
    allowed = _ids(raw.get("allowed_group_ids", []), "allowed_group_ids")
    trusted = _ids(raw.get("trusted_group_ids", []), "trusted_group_ids")
    if not trusted.issubset(allowed):
        raise ValueError("trusted_group_ids must be a subset of allowed_group_ids")

    modes: dict[int, str] = {chat_id: "adaptive" for chat_id in allowed}
    for chat_id, mode in raw.get("group_modes", {}).items():
        numeric_id = int(chat_id)
        mode = str(mode).lower()
        if numeric_id not in allowed or mode not in GROUP_MODES:
            raise ValueError("group_modes must target an allowed group and use a valid mode")
        modes[numeric_id] = mode

    default_agent = str(raw.get("default_group_agent", agents[0].key))
    if default_agent not in seen:
        raise ValueError("default_group_agent does not name a configured agent")
    state_dir = _path(raw.get("state_dir", "/var/lib/sutang-telegram-bridge"))
    assert state_dir is not None

    transcription: TranscriptionConfig | None = None
    transcription_raw = raw.get("transcription")
    if transcription_raw is not None:
        if not isinstance(transcription_raw, dict):
            raise ValueError("transcription must be a JSON object")
        transcriber_command = transcription_raw.get("command")
        if not isinstance(transcriber_command, list) or not transcriber_command or not all(
            isinstance(part, str) and part for part in transcriber_command
        ):
            raise ValueError("transcription.command must be a non-empty argv array")
        if not Path(transcriber_command[0]).is_absolute():
            raise ValueError("transcription.command[0] must be an absolute path")
        transcriber_env = tuple(str(v) for v in transcription_raw.get("pass_env", []))
        if token_env_names.intersection(transcriber_env):
            raise ValueError("transcription.pass_env must not include Telegram token variables")
        transcription = TranscriptionConfig(
            command=tuple(transcriber_command),
            pass_env=transcriber_env,
            timeout_seconds=float(transcription_raw.get("timeout_seconds", 120)),
            max_chars=int(transcription_raw.get("max_chars", 12000)),
        )
        if not 10 <= transcription.timeout_seconds <= 1800 or transcription.max_chars <= 0:
            raise ValueError("transcription timeout/max_chars are outside allowed limits")

    config = BridgeConfig(
        agents=tuple(agents),
        owner_ids=owner_ids,
        allowed_group_ids=allowed,
        trusted_group_ids=trusted,
        group_modes=modes,
        default_group_agent=default_agent,
        state_dir=state_dir,
        transcription=transcription,
        silent_reaction=str(raw.get("silent_reaction", "")),
        max_attachment_bytes=_positive_int(raw, "max_attachment_bytes", 20 * 1024 * 1024),
        max_attachments=_positive_int(raw, "max_attachments", 8),
        max_archive_files=_positive_int(raw, "max_archive_files", 256),
        max_archive_bytes=_positive_int(raw, "max_archive_bytes", 100 * 1024 * 1024),
        agent_timeout_seconds=float(raw.get("agent_timeout_seconds", 180)),
        context_messages=_positive_int(raw, "context_messages", 24),
        discussion_max_rounds=min(5, _positive_int(raw, "discussion_max_rounds", 5)),
        bot_pair_call_limit=_positive_int(raw, "bot_pair_call_limit", 4),
        bot_pair_window_seconds=float(raw.get("bot_pair_window_seconds", 120)),
        group_bot_call_limit=_positive_int(raw, "group_bot_call_limit", 8),
        group_session_max_turns=_positive_int(
            raw, "group_session_max_turns", 40
        ),
        group_session_max_age_seconds=float(
            raw.get("group_session_max_age_seconds", 86400)
        ),
    )
    if not 10 <= config.agent_timeout_seconds <= 1800:
        raise ValueError("agent_timeout_seconds must be between 10 and 1800")
    if len(config.silent_reaction) > 16 or any(ord(char) < 32 for char in config.silent_reaction):
        raise ValueError("silent_reaction is invalid")
    if not 1 <= config.bot_pair_call_limit <= 20:
        raise ValueError("bot_pair_call_limit must be between 1 and 20")
    if not 1 <= config.bot_pair_window_seconds <= 3600:
        raise ValueError("bot_pair_window_seconds must be between 1 and 3600")
    if not 1 <= config.group_bot_call_limit <= 100:
        raise ValueError("group_bot_call_limit must be between 1 and 100")
    if not 1 <= config.group_session_max_turns <= 200:
        raise ValueError("group_session_max_turns must be between 1 and 200")
    if not 60 <= config.group_session_max_age_seconds <= 7 * 86400:
        raise ValueError(
            "group_session_max_age_seconds must be between 60 and 604800"
        )
    return config, tokens
