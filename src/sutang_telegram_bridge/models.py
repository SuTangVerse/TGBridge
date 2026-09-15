from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    key: str
    token_env: str
    command: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    private_cwd: Path | None = None
    group_cwd: Path | None = None
    media_root: Path | None = None
    attachment_group: str | None = None
    pass_env: tuple[str, ...] = ()
    incremental_group_sessions: bool = False


@dataclass(frozen=True)
class TranscriptionConfig:
    command: tuple[str, ...]
    pass_env: tuple[str, ...] = ()
    timeout_seconds: float = 120.0
    max_chars: int = 12000


@dataclass(frozen=True)
class BridgeConfig:
    agents: tuple[AgentConfig, ...]
    owner_ids: frozenset[int]
    allowed_group_ids: frozenset[int]
    trusted_group_ids: frozenset[int]
    group_modes: dict[int, str]
    default_group_agent: str
    state_dir: Path
    transcription: TranscriptionConfig | None = None
    silent_reaction: str = ""
    max_attachment_bytes: int = 20 * 1024 * 1024
    max_attachments: int = 8
    max_archive_files: int = 256
    max_archive_bytes: int = 100 * 1024 * 1024
    agent_timeout_seconds: float = 180.0
    context_messages: int = 24
    discussion_max_rounds: int = 5
    bot_pair_call_limit: int = 4
    bot_pair_window_seconds: float = 120.0
    group_bot_call_limit: int = 8
    group_session_max_turns: int = 40
    group_session_max_age_seconds: float = 86400.0


@dataclass(frozen=True)
class BotIdentity:
    id: int
    username: str


@dataclass(frozen=True)
class IncomingMessage:
    bot_key: str
    update_id: int
    chat_id: int
    chat_type: str
    message_id: int
    thread_id: int | None
    sender_id: int
    sender_name: str
    sender_username: str
    sender_is_bot: bool
    text: str
    reply_to: dict[str, Any] | None
    raw_message: dict[str, Any] = field(repr=False)
    event_type: str = "message"
    callback_query_id: str = ""
    callback_data: str = ""
    chat_title: str = ""

    @property
    def is_private(self) -> bool:
        return self.chat_type == "private"
