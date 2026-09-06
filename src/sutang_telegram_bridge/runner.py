from __future__ import annotations

import asyncio
import os
import re
import signal
from pathlib import Path

from .models import AgentConfig

MAX_OUTPUT_BYTES = 1_000_000
SECRET_RE = re.compile(
    r"(?:[0-9]{7,12}:[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})"
)


class AgentRunner:
    async def run(
        self, agent: AgentConfig, prompt: str, private: bool, timeout: float
    ) -> str:
        cwd: Path | None = agent.private_cwd if private else agent.group_cwd
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
        for name in agent.pass_env:
            if name in os.environ:
                env[name] = os.environ[name]

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
            raise RuntimeError(f"agent exited {process.returncode}: {summary}")
        answer = stdout.decode("utf-8", "replace").strip()
        if not answer:
            raise RuntimeError("agent returned an empty response")
        return answer
