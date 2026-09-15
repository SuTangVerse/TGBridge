from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GroupBotReservation:
    allowed: bool
    call_id: str
    epoch: int
    reason: str


class DeliveryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self._create_schema()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _create_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS updates (
                bot_key TEXT NOT NULL,
                update_id INTEGER NOT NULL,
                chat_id INTEGER,
                message_id INTEGER,
                payload TEXT,
                state TEXT NOT NULL DEFAULT 'received',
                attempts INTEGER NOT NULL DEFAULT 0,
                response TEXT,
                error TEXT,
                updated_at REAL NOT NULL,
                PRIMARY KEY (bot_key, update_id)
            );
            CREATE INDEX IF NOT EXISTS updates_state_idx ON updates(state, updated_at);

            CREATE TABLE IF NOT EXISTS claims (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                claimed_at REAL NOT NULL,
                PRIMARY KEY (chat_id, message_id, kind)
            );

            CREATE TABLE IF NOT EXISTS bot_pair_calls (
                call_id TEXT PRIMARY KEY,
                surface TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                thread_key INTEGER NOT NULL,
                source_bot_id INTEGER NOT NULL,
                target_bot_id INTEGER NOT NULL,
                pair_low INTEGER NOT NULL,
                pair_high INTEGER NOT NULL,
                admitted_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS bot_pair_calls_pair_idx
                ON bot_pair_calls(pair_low, pair_high, admitted_at);

            CREATE TABLE IF NOT EXISTS group_flows (
                chat_id INTEGER NOT NULL,
                thread_key INTEGER NOT NULL,
                epoch INTEGER NOT NULL DEFAULT 0,
                source_message_id INTEGER NOT NULL DEFAULT 0,
                bot_calls INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chat_id, thread_key)
            );

            CREATE TABLE IF NOT EXISTS context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_key TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                thread_key INTEGER NOT NULL,
                role TEXT NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS context_lookup_idx
                ON context(agent_key, chat_id, thread_key, id DESC);

            CREATE TABLE IF NOT EXISTS participants (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                username TEXT NOT NULL,
                is_owner INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS media_assets (
                asset_id TEXT PRIMARY KEY,
                bot_key TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE (bot_key, chat_id, kind, file_id)
            );

            CREATE TABLE IF NOT EXISTS dynamic_group_modes (
                chat_id INTEGER PRIMARY KEY,
                mode TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_pauses (
                agent_key TEXT PRIMARY KEY,
                paused INTEGER NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_group_pauses (
                agent_key TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                paused INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (agent_key, chat_id)
            );

            CREATE TABLE IF NOT EXISTS known_groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                trust_state TEXT NOT NULL,
                decision_id TEXT NOT NULL UNIQUE,
                notification_bot TEXT NOT NULL,
                first_seen_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS anomaly_notices (
                notice_id TEXT PRIMARY KEY,
                request_key TEXT NOT NULL UNIQUE,
                bot_key TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                error_type TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                request_key TEXT NOT NULL UNIQUE,
                bot_key TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                thread_key INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                options_json TEXT NOT NULL,
                state TEXT NOT NULL,
                selected_id TEXT,
                selected_label TEXT,
                decided_by INTEGER,
                decision_update_id INTEGER,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                decided_at REAL
            );

            CREATE TABLE IF NOT EXISTS group_scene_consents (
                scene_id TEXT PRIMARY KEY,
                request_key TEXT NOT NULL UNIQUE,
                bot_key TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                thread_key INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                source_update_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                chat_title TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                sender_username TEXT NOT NULL,
                source_text TEXT NOT NULL,
                reply_json TEXT NOT NULL,
                raw_message_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                request_expires_at REAL NOT NULL,
                active_expires_at REAL,
                decided_at REAL,
                decision_update_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS group_scene_scope_idx
                ON group_scene_consents(
                    bot_key, chat_id, thread_key, owner_id, state
                );
            """
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def recover(self) -> None:
        with self.db:
            self.db.execute(
                "UPDATE updates SET state='received', updated_at=? WHERE state='processing'",
                (time.time(),),
            )

    def put_update(
        self,
        bot_key: str,
        update_id: int,
        payload: dict[str, Any],
        chat_id: int | None,
        message_id: int | None,
    ) -> bool:
        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO updates
                    (bot_key, update_id, chat_id, message_id, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_key,
                    update_id,
                    chat_id,
                    message_id,
                    json.dumps(payload, ensure_ascii=False),
                    time.time(),
                ),
            )
        return cursor.rowcount == 1

    def get_update(self, bot_key: str, update_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM updates WHERE bot_key=? AND update_id=?",
            (bot_key, update_id),
        ).fetchone()

    def pending(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                """
                SELECT * FROM updates
                WHERE state IN ('received', 'generated') AND attempts < 5
                ORDER BY updated_at ASC LIMIT ?
                """,
                (limit,),
            )
        )

    def set_processing(self, bot_key: str, update_id: int) -> None:
        with self.db:
            self.db.execute(
                """
                UPDATE updates SET state='processing', attempts=attempts+1,
                    error=NULL, updated_at=?
                WHERE bot_key=? AND update_id=?
                """,
                (time.time(), bot_key, update_id),
            )

    def set_generated(
        self, bot_key: str, update_id: int, operations: list[dict[str, Any]]
    ) -> None:
        with self.db:
            self.db.execute(
                """
                UPDATE updates SET state='generated', response=?, updated_at=?
                WHERE bot_key=? AND update_id=?
                """,
                (json.dumps(operations, ensure_ascii=False), time.time(), bot_key, update_id),
            )

    def retry(self, bot_key: str, update_id: int, error: str) -> None:
        with self.db:
            row = self.get_update(bot_key, update_id)
            state = "dead" if row and int(row["attempts"]) >= 5 else "received"
            self.db.execute(
                """
                UPDATE updates SET state=?, error=?, updated_at=?
                WHERE bot_key=? AND update_id=?
                """,
                (state, error[:500], time.time(), bot_key, update_id),
            )

    def delivery_failed(self, bot_key: str, update_id: int, error: str) -> None:
        with self.db:
            self.db.execute(
                """
                UPDATE updates SET
                    state=CASE WHEN attempts + 1 >= 5 THEN 'dead' ELSE 'generated' END,
                    attempts=attempts+1, error=?, updated_at=?
                WHERE bot_key=? AND update_id=?
                """,
                (error[:500], time.time(), bot_key, update_id),
            )

    def done(self, bot_key: str, update_id: int) -> None:
        with self.db:
            self.db.execute(
                """
                UPDATE updates SET state='done', payload=NULL, response=NULL,
                    error=NULL, updated_at=? WHERE bot_key=? AND update_id=?
                """,
                (time.time(), bot_key, update_id),
            )

    def prune_raw_payloads(self, max_age_seconds: float = 86400.0) -> None:
        cutoff = time.time() - max_age_seconds
        with self.db:
            self.db.execute(
                "UPDATE updates SET payload=NULL WHERE state='dead' AND updated_at < ?",
                (cutoff,),
            )

    def claim(self, chat_id: int, message_id: int, kind: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO claims VALUES (?, ?, ?, ?)",
                (chat_id, message_id, kind, time.time()),
            )
        return cursor.rowcount == 1

    def reserve_bot_pair_call(
        self,
        *,
        call_id: str,
        surface: str,
        chat_id: int,
        thread_id: int | None,
        source_bot_id: int,
        target_bot_id: int,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> bool:
        """Reserve one unordered bot-pair call before invoking an Agent."""
        stamp = time.time() if now is None else float(now)
        source_bot_id = int(source_bot_id)
        target_bot_id = int(target_bot_id)
        if not source_bot_id or not target_bot_id or source_bot_id == target_bot_id:
            return False
        pair_low, pair_high = sorted((source_bot_id, target_bot_id))
        cutoff = stamp - max(1.0, float(window_seconds))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute(
                "SELECT 1 FROM bot_pair_calls WHERE call_id=?", (str(call_id),)
            ).fetchone():
                self.db.commit()
                return False
            self.db.execute(
                "DELETE FROM bot_pair_calls WHERE admitted_at < ?",
                (stamp - max(86400.0, float(window_seconds)),),
            )
            count = int(
                self.db.execute(
                    """
                    SELECT COUNT(*) FROM bot_pair_calls
                    WHERE pair_low=? AND pair_high=? AND admitted_at>=?
                    """,
                    (pair_low, pair_high, cutoff),
                ).fetchone()[0]
            )
            if count >= max(1, int(limit)):
                self.db.commit()
                return False
            self.db.execute(
                """
                INSERT INTO bot_pair_calls
                    (call_id, surface, chat_id, thread_key, source_bot_id,
                     target_bot_id, pair_low, pair_high, admitted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(call_id),
                    str(surface),
                    int(chat_id),
                    int(thread_id or 0),
                    source_bot_id,
                    target_bot_id,
                    pair_low,
                    pair_high,
                    stamp,
                ),
            )
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def begin_group_epoch(
        self,
        chat_id: int,
        thread_id: int | None,
        source_message_id: int,
        *,
        now: float | None = None,
    ) -> int:
        """Open one causal epoch per human group message across all bot copies."""
        stamp = time.time() if now is None else float(now)
        chat_id = int(chat_id)
        thread_key = int(thread_id or 0)
        source_message_id = int(source_message_id)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """
                INSERT OR IGNORE INTO group_flows
                    (chat_id, thread_key, epoch, source_message_id, bot_calls, updated_at)
                VALUES (?, ?, 0, 0, 0, ?)
                """,
                (chat_id, thread_key, stamp),
            )
            row = self.db.execute(
                """
                SELECT epoch, source_message_id FROM group_flows
                WHERE chat_id=? AND thread_key=?
                """,
                (chat_id, thread_key),
            ).fetchone()
            epoch = int(row["epoch"])
            if source_message_id > int(row["source_message_id"]):
                epoch += 1
                self.db.execute(
                    """
                    UPDATE group_flows SET epoch=?, source_message_id=?,
                        bot_calls=0, updated_at=?
                    WHERE chat_id=? AND thread_key=?
                    """,
                    (epoch, source_message_id, stamp, chat_id, thread_key),
                )
            self.db.commit()
            return epoch
        except Exception:
            self.db.rollback()
            raise

    def current_group_epoch(self, chat_id: int, thread_id: int | None) -> int:
        row = self.db.execute(
            """
            SELECT epoch FROM group_flows WHERE chat_id=? AND thread_key=?
            """,
            (int(chat_id), int(thread_id or 0)),
        ).fetchone()
        return int(row["epoch"]) if row else 0

    def reserve_group_bot_call(
        self,
        *,
        call_id: str,
        chat_id: int,
        thread_id: int | None,
        source_bot_id: int,
        target_bot_id: int,
        pair_limit: int,
        pair_window_seconds: float,
        group_limit: int,
        now: float | None = None,
    ) -> GroupBotReservation:
        """Atomically enforce pair and causal-epoch budgets before model use."""
        stamp = time.time() if now is None else float(now)
        chat_id = int(chat_id)
        thread_key = int(thread_id or 0)
        source_bot_id = int(source_bot_id)
        target_bot_id = int(target_bot_id)
        if not source_bot_id or not target_bot_id or source_bot_id == target_bot_id:
            return GroupBotReservation(False, str(call_id), 0, "invalid_pair")
        pair_low, pair_high = sorted((source_bot_id, target_bot_id))
        cutoff = stamp - max(1.0, float(pair_window_seconds))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """
                INSERT OR IGNORE INTO group_flows
                    (chat_id, thread_key, epoch, source_message_id, bot_calls, updated_at)
                VALUES (?, ?, 0, 0, 0, ?)
                """,
                (chat_id, thread_key, stamp),
            )
            flow = self.db.execute(
                """
                SELECT epoch, bot_calls FROM group_flows
                WHERE chat_id=? AND thread_key=?
                """,
                (chat_id, thread_key),
            ).fetchone()
            epoch = int(flow["epoch"])
            if self.db.execute(
                "SELECT 1 FROM bot_pair_calls WHERE call_id=?", (str(call_id),)
            ).fetchone():
                self.db.commit()
                return GroupBotReservation(False, str(call_id), epoch, "duplicate")
            self.db.execute(
                "DELETE FROM bot_pair_calls WHERE admitted_at < ?",
                (stamp - max(86400.0, float(pair_window_seconds)),),
            )
            pair_count = int(
                self.db.execute(
                    """
                    SELECT COUNT(*) FROM bot_pair_calls
                    WHERE pair_low=? AND pair_high=? AND admitted_at>=?
                    """,
                    (pair_low, pair_high, cutoff),
                ).fetchone()[0]
            )
            if pair_count >= max(1, int(pair_limit)):
                self.db.commit()
                return GroupBotReservation(False, str(call_id), epoch, "pair_limit")
            if int(flow["bot_calls"]) >= max(1, int(group_limit)):
                self.db.commit()
                return GroupBotReservation(False, str(call_id), epoch, "group_limit")
            self.db.execute(
                """
                INSERT INTO bot_pair_calls
                    (call_id, surface, chat_id, thread_key, source_bot_id,
                     target_bot_id, pair_low, pair_high, admitted_at)
                VALUES (?, 'group', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(call_id),
                    chat_id,
                    thread_key,
                    source_bot_id,
                    target_bot_id,
                    pair_low,
                    pair_high,
                    stamp,
                ),
            )
            self.db.execute(
                """
                UPDATE group_flows SET bot_calls=bot_calls+1, updated_at=?
                WHERE chat_id=? AND thread_key=? AND epoch=?
                """,
                (stamp, chat_id, thread_key, epoch),
            )
            self.db.commit()
            return GroupBotReservation(True, str(call_id), epoch, "admitted")
        except Exception:
            self.db.rollback()
            raise

    def group_flow_status(
        self,
        chat_id: int,
        thread_id: int | None,
        *,
        pair_window_seconds: float,
        now: float | None = None,
    ) -> dict[str, Any]:
        stamp = time.time() if now is None else float(now)
        chat_id = int(chat_id)
        thread_key = int(thread_id or 0)
        row = self.db.execute(
            """
            SELECT epoch, source_message_id, bot_calls FROM group_flows
            WHERE chat_id=? AND thread_key=?
            """,
            (chat_id, thread_key),
        ).fetchone()
        pairs = self.db.execute(
            """
            SELECT pair_low, pair_high, COUNT(*) AS call_count,
                   MAX(admitted_at) AS last_at
            FROM bot_pair_calls
            WHERE admitted_at>=?
            GROUP BY pair_low, pair_high ORDER BY pair_low, pair_high
            """,
            (stamp - max(1.0, float(pair_window_seconds)),),
        ).fetchall()
        return {
            "epoch": int(row["epoch"]) if row else 0,
            "source_message_id": int(row["source_message_id"]) if row else 0,
            "bot_calls": int(row["bot_calls"]) if row else 0,
            "pairs": [
                {
                    "pair_low": int(item["pair_low"]),
                    "pair_high": int(item["pair_high"]),
                    "call_count": int(item["call_count"]),
                    "last_at": float(item["last_at"]),
                }
                for item in pairs
            ],
        }

    def add_context(
        self,
        agent_key: str,
        chat_id: int,
        thread_id: int | None,
        role: str,
        speaker: dict[str, Any],
        text: str,
        keep: int,
    ) -> int:
        thread_key = thread_id or 0
        with self.db:
            cursor = self.db.execute(
                """
                INSERT INTO context
                    (agent_key, chat_id, thread_key, role, speaker, text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_key,
                    chat_id,
                    thread_key,
                    role,
                    json.dumps(speaker, ensure_ascii=False),
                    text[:48000],
                    time.time(),
                ),
            )
            self.db.execute(
                """
                DELETE FROM context WHERE agent_key=? AND chat_id=? AND thread_key=?
                AND id NOT IN (
                    SELECT id FROM context WHERE agent_key=? AND chat_id=? AND thread_key=?
                    ORDER BY id DESC LIMIT ?
                )
                """,
                (
                    agent_key,
                    chat_id,
                    thread_key,
                    agent_key,
                    chat_id,
                    thread_key,
                    keep,
                ),
            )
        return int(cursor.lastrowid)

    def get_context(
        self, agent_key: str, chat_id: int, thread_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT role, speaker, text FROM context
            WHERE agent_key=? AND chat_id=? AND thread_key=?
            ORDER BY id DESC LIMIT ?
            """,
            (agent_key, chat_id, thread_id or 0, limit),
        ).fetchall()
        return [
            {"role": row["role"], "speaker": json.loads(row["speaker"]), "text": row["text"]}
            for row in reversed(rows)
        ]

    def get_context_after(
        self,
        agent_key: str,
        chat_id: int,
        thread_id: int | None,
        after_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return every still-buffered context row after a committed cursor."""
        rows = self.db.execute(
            """
            SELECT id, role, speaker, text FROM context
            WHERE agent_key=? AND chat_id=? AND thread_key=? AND id>?
            ORDER BY id ASC LIMIT ?
            """,
            (agent_key, chat_id, thread_id or 0, max(0, int(after_id)), limit),
        ).fetchall()
        return [
            {
                "context_id": int(row["id"]),
                "role": row["role"],
                "speaker": json.loads(row["speaker"]),
                "text": row["text"],
            }
            for row in rows
        ]

    def clear_context(
        self, agent_key: str, chat_id: int, thread_id: int | None
    ) -> None:
        with self.db:
            self.db.execute(
                """
                DELETE FROM context
                WHERE agent_key=? AND chat_id=? AND thread_key=?
                """,
                (agent_key, int(chat_id), int(thread_id or 0)),
            )

    def remember_participant(
        self,
        chat_id: int,
        user_id: int,
        display_name: str,
        username: str,
        is_owner: bool,
    ) -> None:
        with self.db:
            self.db.execute(
                """
                INSERT INTO participants VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    username=excluded.username,
                    is_owner=excluded.is_owner,
                    updated_at=excluded.updated_at
                """,
                (chat_id, user_id, display_name, username, int(is_owner), time.time()),
            )

    def participant_aliases(self, chat_id: int) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT user_id, display_name, username, is_owner FROM participants WHERE chat_id=?",
                (chat_id,),
            )
        )

    def register_asset(
        self, bot_key: str, chat_id: int, kind: str, file_id: str
    ) -> str:
        row = self.db.execute(
            """
            SELECT asset_id FROM media_assets
            WHERE bot_key=? AND chat_id=? AND kind=? AND file_id=?
            """,
            (bot_key, chat_id, kind, file_id),
        ).fetchone()
        if row:
            return str(row["asset_id"])
        asset_id = "tg_" + secrets.token_hex(8)
        with self.db:
            self.db.execute(
                "INSERT INTO media_assets VALUES (?, ?, ?, ?, ?, ?)",
                (asset_id, bot_key, chat_id, kind, file_id, time.time()),
            )
        return asset_id

    def resolve_asset(
        self, bot_key: str, chat_id: int, asset_id: str, kind: str
    ) -> str | None:
        row = self.db.execute(
            """
            SELECT file_id FROM media_assets
            WHERE asset_id=? AND bot_key=? AND chat_id=? AND kind=?
            """,
            (asset_id, bot_key, chat_id, kind),
        ).fetchone()
        return str(row["file_id"]) if row else None

    def set_group_mode(self, chat_id: int, mode: str) -> None:
        if mode not in {"adaptive", "full", "mentions", "muted"}:
            raise ValueError("invalid group mode")
        with self.db:
            self.db.execute(
                """
                INSERT INTO dynamic_group_modes VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET mode=excluded.mode, updated_at=excluded.updated_at
                """,
                (chat_id, mode, time.time()),
            )

    def group_mode(self, chat_id: int) -> str | None:
        row = self.db.execute(
            "SELECT mode FROM dynamic_group_modes WHERE chat_id=?", (chat_id,)
        ).fetchone()
        return str(row["mode"]) if row else None

    def set_agent_paused(self, agent_key: str, paused: bool) -> None:
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_pauses VALUES (?, ?, ?)
                ON CONFLICT(agent_key) DO UPDATE SET paused=excluded.paused, updated_at=excluded.updated_at
                """,
                (agent_key, int(paused), time.time()),
            )

    def agent_paused(self, agent_key: str) -> bool:
        row = self.db.execute(
            "SELECT paused FROM agent_pauses WHERE agent_key=?", (agent_key,)
        ).fetchone()
        return bool(row["paused"]) if row else False

    def set_agent_group_paused(
        self, agent_key: str, chat_id: int, paused: bool
    ) -> None:
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_group_pauses VALUES (?, ?, ?, ?)
                ON CONFLICT(agent_key, chat_id) DO UPDATE SET
                    paused=excluded.paused, updated_at=excluded.updated_at
                """,
                (agent_key, int(chat_id), int(paused), time.time()),
            )

    def agent_group_paused(self, agent_key: str, chat_id: int) -> bool:
        row = self.db.execute(
            """
            SELECT paused FROM agent_group_pauses
            WHERE agent_key=? AND chat_id=?
            """,
            (agent_key, int(chat_id)),
        ).fetchone()
        return bool(row["paused"]) if row else False

    def register_group(
        self,
        chat_id: int,
        title: str,
        *,
        trust_state: str = "pending",
        notification_bot: str = "",
    ) -> tuple[sqlite3.Row, bool]:
        if trust_state not in {"pending", "trusted", "external"}:
            raise ValueError("invalid group trust state")
        now = time.time()
        decision_id = secrets.token_hex(8)
        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO known_groups
                    (chat_id, title, trust_state, decision_id, notification_bot,
                     first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(chat_id),
                    str(title)[:200],
                    trust_state,
                    decision_id,
                    notification_bot,
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 0 and title:
                self.db.execute(
                    """
                    UPDATE known_groups SET title=?, updated_at=? WHERE chat_id=?
                    """,
                    (str(title)[:200], now, int(chat_id)),
                )
        row = self.group_record(chat_id)
        if row is None:
            raise RuntimeError("group registration disappeared")
        return row, cursor.rowcount == 1

    def group_record(self, chat_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM known_groups WHERE chat_id=?", (int(chat_id),)
        ).fetchone()

    def known_groups(self, state: str = "") -> list[sqlite3.Row]:
        if state:
            return list(
                self.db.execute(
                    """
                    SELECT * FROM known_groups WHERE trust_state=?
                    ORDER BY updated_at DESC
                    """,
                    (state,),
                )
            )
        return list(
            self.db.execute(
                "SELECT * FROM known_groups ORDER BY updated_at DESC"
            )
        )

    def resolve_group_decision(
        self, decision_id: str, bot_key: str, trust_state: str
    ) -> sqlite3.Row | None:
        if trust_state not in {"trusted", "external"}:
            return None
        with self.db:
            cursor = self.db.execute(
                """
                UPDATE known_groups SET trust_state=?, updated_at=?
                WHERE decision_id=? AND notification_bot=? AND trust_state='pending'
                """,
                (trust_state, time.time(), decision_id, bot_key),
            )
        if cursor.rowcount != 1:
            return None
        return self.db.execute(
            "SELECT * FROM known_groups WHERE decision_id=?", (decision_id,)
        ).fetchone()

    def ensure_anomaly_notice(
        self,
        *,
        request_key: str,
        bot_key: str,
        chat_id: int,
        owner_id: int,
        error_type: str,
    ) -> sqlite3.Row:
        now = time.time()
        with self.db:
            self.db.execute(
                """
                INSERT OR IGNORE INTO anomaly_notices
                    (notice_id, request_key, bot_key, chat_id, owner_id,
                     error_type, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    secrets.token_hex(8),
                    request_key,
                    bot_key,
                    int(chat_id),
                    int(owner_id),
                    str(error_type)[:100],
                    now,
                    now,
                ),
            )
        row = self.db.execute(
            "SELECT * FROM anomaly_notices WHERE request_key=?", (request_key,)
        ).fetchone()
        if row is None:
            raise RuntimeError("anomaly notice disappeared")
        return row

    def mark_anomaly_notified(self, notice_id: str) -> None:
        with self.db:
            self.db.execute(
                """
                UPDATE anomaly_notices SET state='sent', updated_at=?
                WHERE notice_id=?
                """,
                (time.time(), notice_id),
            )

    def anomaly_notice(self, notice_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM anomaly_notices WHERE notice_id=?", (notice_id,)
        ).fetchone()

    def delivery_stats(self, bot_key: str) -> dict[str, int]:
        stats = {
            "received": 0,
            "processing": 0,
            "generated": 0,
            "dead": 0,
            "done": 0,
        }
        rows = self.db.execute(
            """
            SELECT state, COUNT(*) AS count FROM updates
            WHERE bot_key=? GROUP BY state
            """,
            (bot_key,),
        ).fetchall()
        stats.update({str(row["state"]): int(row["count"]) for row in rows})
        return stats

    def dead_letters(self, bot_key: str, limit: int = 10) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                """
                SELECT update_id, error, updated_at FROM updates
                WHERE bot_key=? AND state='dead'
                ORDER BY updated_at DESC LIMIT ?
                """,
                (bot_key, int(limit)),
            )
        )

    def requeue_dead(self, bot_key: str, update_id: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                """
                UPDATE updates SET state='received', attempts=0, error=NULL,
                    updated_at=?
                WHERE bot_key=? AND update_id=? AND state='dead'
                    AND payload IS NOT NULL
                """,
                (time.time(), bot_key, int(update_id)),
            )
        return cursor.rowcount == 1

    def create_approval(
        self,
        *,
        request_key: str,
        bot_key: str,
        chat_id: int,
        thread_id: int | None,
        source_message_id: int,
        title: str,
        detail: str,
        options: list[dict[str, str]],
        ttl_seconds: float = 86400.0,
    ) -> str:
        existing = self.db.execute(
            "SELECT approval_id FROM approvals WHERE request_key=?", (request_key,)
        ).fetchone()
        if existing:
            return str(existing["approval_id"])
        approval_id = secrets.token_hex(8)
        now = time.time()
        with self.db:
            self.db.execute(
                """
                INSERT INTO approvals VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, NULL, ?, ?, NULL)
                """,
                (
                    approval_id,
                    request_key,
                    bot_key,
                    chat_id,
                    thread_id or 0,
                    source_message_id,
                    title,
                    detail,
                    json.dumps(options, ensure_ascii=False),
                    now,
                    now + ttl_seconds,
                ),
            )
        return approval_id

    def resolve_approval(
        self,
        approval_id: str,
        option_id: str,
        *,
        bot_key: str,
        chat_id: int,
        owner_id: int,
        update_id: int,
    ) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
        ).fetchone()
        if row is None or str(row["bot_key"]) != bot_key or int(row["chat_id"]) != chat_id:
            return {"status": "unknown"}
        if row["state"] == "resolved":
            status = "replay" if int(row["decision_update_id"] or -1) == update_id else "already"
            return {"status": status, **dict(row)}
        if float(row["expires_at"]) < time.time():
            with self.db:
                self.db.execute(
                    "UPDATE approvals SET state='expired' WHERE approval_id=? AND state='pending'",
                    (approval_id,),
                )
            return {"status": "expired"}
        options = json.loads(str(row["options_json"]))
        selected = next((item for item in options if item["id"] == option_id), None)
        if selected is None:
            return {"status": "invalid"}
        now = time.time()
        with self.db:
            cursor = self.db.execute(
                """
                UPDATE approvals SET state='resolved', selected_id=?, selected_label=?,
                    decided_by=?, decision_update_id=?, decided_at=?
                WHERE approval_id=? AND state='pending'
                """,
                (option_id, selected["label"], owner_id, update_id, now, approval_id),
            )
        if cursor.rowcount != 1:
            return {"status": "already"}
        resolved = self.db.execute(
            "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
        ).fetchone()
        return {"status": "resolved", **dict(resolved)}

    def create_group_scene_request(
        self,
        *,
        request_key: str,
        bot_key: str,
        chat_id: int,
        thread_id: int | None,
        owner_id: int,
        source_update_id: int,
        source_message_id: int,
        chat_title: str,
        sender_name: str,
        sender_username: str,
        source_text: str,
        reply_to: dict[str, Any] | None,
        raw_message: dict[str, Any],
        summary: str,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[sqlite3.Row, bool]:
        stamp = time.time() if now is None else float(now)
        existing = self.db.execute(
            "SELECT * FROM group_scene_consents WHERE request_key=?",
            (str(request_key),),
        ).fetchone()
        if existing is not None:
            return existing, False
        scene_id = secrets.token_hex(8)
        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO group_scene_consents (
                    scene_id, request_key, bot_key, chat_id, thread_key,
                    owner_id, source_update_id, source_message_id, chat_title,
                    sender_name, sender_username, source_text, reply_json,
                    raw_message_json, summary, state, created_at, request_expires_at,
                    active_expires_at, decided_at, decision_update_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'pending', ?, ?, NULL, NULL, NULL)
                """,
                (
                    scene_id,
                    str(request_key),
                    str(bot_key),
                    int(chat_id),
                    int(thread_id or 0),
                    int(owner_id),
                    int(source_update_id),
                    int(source_message_id),
                    str(chat_title)[:200],
                    str(sender_name)[:200],
                    str(sender_username)[:100],
                    str(source_text)[:12000],
                    json.dumps(reply_to or {}, ensure_ascii=False)[:24000],
                    json.dumps(raw_message, ensure_ascii=False)[:64000],
                    str(summary)[:240],
                    stamp,
                    stamp + max(1.0, float(ttl_seconds)),
                ),
            )
        row = self.db.execute(
            "SELECT * FROM group_scene_consents WHERE request_key=?",
            (str(request_key),),
        ).fetchone()
        if row is None:
            raise RuntimeError("group scene request disappeared")
        return row, cursor.rowcount == 1

    def decide_group_scene(
        self,
        scene_id: str,
        action: str,
        *,
        bot_key: str,
        owner_id: int,
        update_id: int,
        active_ttl_seconds: float,
        now: float | None = None,
    ) -> dict[str, Any]:
        stamp = time.time() if now is None else float(now)
        if action not in {"allow", "deny"}:
            return {"status": "invalid"}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM group_scene_consents WHERE scene_id=?",
                (str(scene_id),),
            ).fetchone()
            if (
                row is None
                or str(row["bot_key"]) != str(bot_key)
                or int(row["owner_id"]) != int(owner_id)
            ):
                self.db.commit()
                return {"status": "unknown"}
            if str(row["state"]) == "active" and action == "allow":
                self.db.commit()
                status = (
                    "replay"
                    if int(row["decision_update_id"] or -1) == int(update_id)
                    else "already"
                )
                return {"status": status, **dict(row)}
            if str(row["state"]) != "pending":
                self.db.commit()
                return {"status": "already"}
            if float(row["request_expires_at"]) < stamp:
                self.db.execute(
                    """
                    UPDATE group_scene_consents
                    SET state='expired', decided_at=?, source_text='',
                        reply_json='{}', raw_message_json='{}'
                    WHERE scene_id=?
                    """,
                    (stamp, str(scene_id)),
                )
                self.db.commit()
                return {"status": "expired"}
            if action == "deny":
                self.db.execute(
                    """
                    UPDATE group_scene_consents
                    SET state='denied', decided_at=?, decision_update_id=?,
                        source_text='', reply_json='{}', raw_message_json='{}'
                    WHERE scene_id=?
                    """,
                    (stamp, int(update_id), str(scene_id)),
                )
                self.db.commit()
                return {"status": "denied", **dict(row)}
            self.db.execute(
                """
                UPDATE group_scene_consents SET state='closed', decided_at=?,
                    source_text='', reply_json='{}', raw_message_json='{}'
                WHERE bot_key=? AND chat_id=? AND thread_key=? AND owner_id=?
                  AND state IN ('pending', 'active') AND scene_id<>?
                """,
                (
                    stamp,
                    str(bot_key),
                    int(row["chat_id"]),
                    int(row["thread_key"]),
                    int(owner_id),
                    str(scene_id),
                ),
            )
            self.db.execute(
                """
                UPDATE group_scene_consents
                SET state='active', active_expires_at=?, decided_at=?,
                    decision_update_id=?
                WHERE scene_id=? AND state='pending'
                """,
                (
                    stamp + max(1.0, float(active_ttl_seconds)),
                    stamp,
                    int(update_id),
                    str(scene_id),
                ),
            )
            active = self.db.execute(
                "SELECT * FROM group_scene_consents WHERE scene_id=?",
                (str(scene_id),),
            ).fetchone()
            self.db.commit()
            return {"status": "activated", **dict(active)}
        except Exception:
            self.db.rollback()
            raise

    def active_group_scene(
        self,
        bot_key: str,
        chat_id: int,
        thread_id: int | None,
        owner_id: int,
        *,
        now: float | None = None,
    ) -> sqlite3.Row | None:
        stamp = time.time() if now is None else float(now)
        return self.db.execute(
            """
            SELECT * FROM group_scene_consents
            WHERE bot_key=? AND chat_id=? AND thread_key=? AND owner_id=?
              AND state='active' AND active_expires_at>=?
            ORDER BY decided_at DESC LIMIT 1
            """,
            (
                str(bot_key),
                int(chat_id),
                int(thread_id or 0),
                int(owner_id),
                stamp,
            ),
        ).fetchone()

    def close_group_scene(
        self,
        *,
        bot_key: str,
        owner_id: int,
        scene_id: str | None = None,
        chat_id: int | None = None,
        thread_id: int | None = None,
        now: float | None = None,
    ) -> sqlite3.Row | None:
        stamp = time.time() if now is None else float(now)
        if scene_id is not None:
            row = self.db.execute(
                """
                SELECT * FROM group_scene_consents
                WHERE scene_id=? AND bot_key=? AND owner_id=? AND state='active'
                """,
                (str(scene_id), str(bot_key), int(owner_id)),
            ).fetchone()
        else:
            row = self.db.execute(
                """
                SELECT * FROM group_scene_consents
                WHERE bot_key=? AND chat_id=? AND thread_key=? AND owner_id=?
                  AND state='active'
                ORDER BY decided_at DESC LIMIT 1
                """,
                (
                    str(bot_key),
                    int(chat_id or 0),
                    int(thread_id or 0),
                    int(owner_id),
                ),
            ).fetchone()
        if row is None:
            return None
        with self.db:
            self.db.execute(
                """
                UPDATE group_scene_consents SET state='closed', decided_at=?,
                    source_text='', reply_json='{}', raw_message_json='{}'
                WHERE scene_id=? AND state='active'
                """,
                (stamp, str(row["scene_id"])),
            )
        return row

    def close_group_scenes_for_scope(
        self,
        bot_key: str,
        chat_id: int,
        thread_id: int | None,
        *,
        now: float | None = None,
    ) -> bool:
        stamp = time.time() if now is None else float(now)
        with self.db:
            active = self.db.execute(
                """
                SELECT 1 FROM group_scene_consents
                WHERE bot_key=? AND chat_id=? AND thread_key=?
                  AND state='active' LIMIT 1
                """,
                (str(bot_key), int(chat_id), int(thread_id or 0)),
            ).fetchone()
            self.db.execute(
                """
                UPDATE group_scene_consents SET state='closed', decided_at=?,
                    source_text='', reply_json='{}', raw_message_json='{}'
                WHERE bot_key=? AND chat_id=? AND thread_key=?
                  AND state IN ('pending', 'active')
                """,
                (stamp, str(bot_key), int(chat_id), int(thread_id or 0)),
            )
        return active is not None

    def expire_group_scenes(
        self,
        bot_key: str,
        chat_id: int,
        thread_id: int | None,
        *,
        now: float | None = None,
    ) -> bool:
        stamp = time.time() if now is None else float(now)
        with self.db:
            active = self.db.execute(
                """
                SELECT 1 FROM group_scene_consents
                WHERE bot_key=? AND chat_id=? AND thread_key=?
                  AND state='active' AND active_expires_at<? LIMIT 1
                """,
                (str(bot_key), int(chat_id), int(thread_id or 0), stamp),
            ).fetchone()
            self.db.execute(
                """
                UPDATE group_scene_consents SET state='expired', decided_at=?,
                    source_text='', reply_json='{}', raw_message_json='{}'
                WHERE bot_key=? AND chat_id=? AND thread_key=? AND (
                    (state='active' AND active_expires_at<?) OR
                    (state='pending' AND request_expires_at<?)
                )
                """,
                (
                    stamp,
                    str(bot_key),
                    int(chat_id),
                    int(thread_id or 0),
                    stamp,
                    stamp,
                ),
            )
        return active is not None
