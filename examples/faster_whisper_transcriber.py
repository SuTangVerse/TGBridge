#!/usr/bin/env python3
"""Local faster-whisper adapter: audio path in argv, transcript on stdout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", default="")
    parser.add_argument("audio_file")
    args = parser.parse_args()
    if not Path(args.audio_file).is_file():
        raise SystemExit("audio file does not exist")
    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        args.audio_file,
        language=args.language or None,
        beam_size=5,
        vad_filter=True,
    )
    transcript = " ".join(
        segment.text.strip() for segment in segments if segment.text.strip()
    )
    if not transcript:
        raise SystemExit("no speech detected")
    sys.stdout.write(transcript)


if __name__ == "__main__":
    main()
