from __future__ import annotations

import asyncio
import os
import re
import signal
import json
from pathlib import Path

from .models import AgentConfig

MAX_OUTPUT_BYTES = 1_000_000
SECRET_RE = re.compile(
    r"(?:[0-9]{7,12}:[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})"
)
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
SESSION_MARKER_RE = re.compile(
    r"(?m)^TG_BRIDGE_SESSION_V1\s+(\{[^\r\n]{1,1024}\})\s*$"
)


class SessionResumeError(RuntimeError):
    """The wrapper explicitly rejected a stored provider session."""


class AgentOutput(str):
    """A visible answer carrying an optional opaque provider session id."""

    session_id: str | None

    def __new__(cls, value: str, *, session_id: str | None = None):
        output = super().__new__(cls, value)
        output.session_id = session_id
        return output


def _session_from_stderr(stderr: str) -> str | None:
    matches = SESSION_MARKER_RE.findall(stderr)
    if len(matches) != 1:
        return None
    try:
        value = json.loads(matches[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    session_id = value.get("session_id") if isinstance(value, dict) else None
    return session_id if isinstance(session_id, str) and SESSION_ID_RE.fullmatch(session_id) else None


class AgentRunner:
    async def run(
        self,
        agent: AgentConfig,
        prompt: str,
        private: bool,
        timeout: float,
        *,
        session_id: str | None = None,
    ) -> str:
        if session_id is not None and not SESSION_ID_RE.fullmatch(session_id):
            raise ValueError("invalid stored agent session id")
        cwd: Path | None = agent.private_cwd if private else agent.group_cwd
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
        for name in agent.pass_env:
            if name in os.environ:
                env[name] = os.environ[name]
        env["TG_BRIDGE_SESSION_MODE"] = "resume" if session_id else "fresh"
        if session_id:
            env["TG_BRIDGE_SESSION_ID"] = session_id

        process = await asyncio.create_subprocess_exec(
            *agent.command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")), timeout=timeout
            )
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=3)
            except (ProcessLookupError, TimeoutError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise
        if len(stdout) > MAX_OUTPUT_BYTES or len(stderr) > MAX_OUTPUT_BYTES:
            raise RuntimeError("agent output exceeded 1 MiB")
        if process.returncode != 0:
            summary = stderr.decode("utf-8", "replace").strip()[-500:]
            summary = SECRET_RE.sub("[REDACTED]", summary)
            if session_id and "TG_BRIDGE_SESSION_INVALID" in summary:
                raise SessionResumeError("agent wrapper rejected stored session")
            raise RuntimeError(f"agent exited {process.returncode}: {summary}")
        answer = stdout.decode("utf-8", "replace").strip()
        if not answer:
            raise RuntimeError("agent returned an empty response")
        return AgentOutput(
            answer,
            session_id=_session_from_stderr(stderr.decode("utf-8", "replace")),
        )
