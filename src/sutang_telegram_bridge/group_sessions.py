"""Durable, scope-bound provider sessions for incremental group prompts."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterator


@dataclass(frozen=True)
class GroupSessionSnapshot:
    session_id: str | None
    through_context_id: int
    rotated: bool


class GroupSessionStore:
    """Keep opaque provider sessions apart by Agent, group and Topic.

    The caller supplies a binding derived from the non-secret execution and
    trust scope. Changing that scope, reaching the turn limit, or reaching the
    age limit rotates the provider session before another prompt is sent.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_turns: int = 40,
        max_age_seconds: float = 86400.0,
    ) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.max_turns = max(1, int(max_turns))
        self.max_age_seconds = max(60.0, float(max_age_seconds))
        self._thread_lock = Lock()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with self._thread_lock:
            descriptor = os.open(
                self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _empty_state() -> dict:
        return {"version": 1, "sessions": {}}

    @staticmethod
    def _empty_record() -> dict:
        return {
            "session_id": "",
            "binding": "",
            "through_context_id": 0,
            "turns": 0,
            "created_at": 0.0,
            "updated_at": 0.0,
        }

    def _read_unlocked(self) -> dict:
        try:
            descriptor = os.open(
                self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
            with os.fdopen(descriptor, "r", encoding="utf-8") as source:
                info = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_mode & 0o077
                    or info.st_size > 1024 * 1024
                ):
                    return self._empty_state()
                value = json.load(source)
        except FileNotFoundError:
            return self._empty_state()
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return self._empty_state()
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("sessions"), dict)
        ):
            return self._empty_state()
        return value

    def _save_unlocked(self, state: dict) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".group-sessions-", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(state, output, sort_keys=True, separators=(",", ":"))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _record(self, state: dict, key: str) -> dict:
        sessions = state.setdefault("sessions", {})
        record = sessions.get(key)
        if not isinstance(record, dict):
            record = self._empty_record()
            sessions[key] = record
        for name, value in self._empty_record().items():
            record.setdefault(name, value)
        return record

    def prepare(
        self, key: str, *, binding: str, now: float | None = None
    ) -> GroupSessionSnapshot:
        current = time.time() if now is None else float(now)
        with self._lock():
            state = self._read_unlocked()
            record = self._record(state, key)
            session_id = str(record.get("session_id") or "")
            created_at = float(record.get("created_at") or 0)
            turns = int(record.get("turns") or 0)
            rotated = bool(
                session_id
                and (
                    record.get("binding") != binding
                    or turns >= self.max_turns
                    or (created_at and current - created_at >= self.max_age_seconds)
                )
            )
            if rotated:
                record.update(
                    session_id="",
                    binding=binding,
                    through_context_id=0,
                    turns=0,
                    created_at=0.0,
                    updated_at=current,
                )
                session_id = ""
                self._save_unlocked(state)
            return GroupSessionSnapshot(
                session_id=session_id or None,
                through_context_id=(
                    max(0, int(record.get("through_context_id") or 0))
                    if session_id
                    else 0
                ),
                rotated=rotated,
            )

    def complete(
        self,
        key: str,
        *,
        binding: str,
        previous_session_id: str | None,
        session_id: str | None,
        through_context_id: int,
        now: float | None = None,
    ) -> None:
        current = time.time() if now is None else float(now)
        effective_id = session_id or previous_session_id or ""
        if not effective_id or not binding:
            return
        with self._lock():
            state = self._read_unlocked()
            record = self._record(state, key)
            if previous_session_id and str(record.get("session_id") or "") not in {
                "",
                previous_session_id,
            }:
                return
            continuing = bool(
                previous_session_id
                and str(record.get("session_id") or "") == previous_session_id
                and record.get("binding") == binding
            )
            record.update(
                session_id=effective_id,
                binding=binding,
                through_context_id=max(
                    int(record.get("through_context_id") or 0),
                    max(0, int(through_context_id)),
                ),
                turns=int(record.get("turns") or 0) + 1 if continuing else 1,
                created_at=(
                    float(record.get("created_at") or current)
                    if continuing
                    else current
                ),
                updated_at=current,
            )
            self._save_unlocked(state)

    def discard(self, key: str) -> None:
        with self._lock():
            state = self._read_unlocked()
            record = self._record(state, key)
            record.update(
                session_id="",
                through_context_id=0,
                turns=0,
                created_at=0.0,
                updated_at=time.time(),
            )
            self._save_unlocked(state)

    def discard_prefix(self, prefix: str) -> None:
        """Drop every provider session in one bounded logical scope."""
        with self._lock():
            state = self._read_unlocked()
            sessions = state.setdefault("sessions", {})
            matched = [
                key
                for key in sessions
                if key == prefix or key.startswith(prefix + ":")
            ]
            if not matched:
                return
            for key in matched:
                sessions.pop(key, None)
            self._save_unlocked(state)

    def inspect(self, key: str) -> dict:
        with self._lock():
            return dict(self._record(self._read_unlocked(), key))
