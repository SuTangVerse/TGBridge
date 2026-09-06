from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from .models import TranscriptionConfig

MAX_TRANSCRIBER_OUTPUT_BYTES = 1_000_000


class VoiceTranscriber:
    def __init__(self, config: TranscriptionConfig):
        self.config = config

    async def transcribe(self, audio_path: Path) -> str:
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
        for name in self.config.pass_env:
            if name in os.environ:
                env[name] = os.environ[name]
        process = await asyncio.create_subprocess_exec(
            *self.config.command,
            str(audio_path),
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.config.timeout_seconds
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
        if len(stdout) > MAX_TRANSCRIBER_OUTPUT_BYTES or len(stderr) > MAX_TRANSCRIBER_OUTPUT_BYTES:
            raise RuntimeError("transcriber output exceeded 1 MiB")
        if process.returncode != 0:
            raise RuntimeError(f"transcriber exited {process.returncode}")
        transcript = stdout.decode("utf-8", "replace").strip()
        if not transcript:
            raise RuntimeError("transcriber returned empty text")
        return transcript[: self.config.max_chars]
