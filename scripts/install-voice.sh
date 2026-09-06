#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo ./scripts/install-voice.sh" >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VOICE_DIR=/opt/sutang-telegram-voice
MODEL_DIR=$VOICE_DIR/faster-whisper-small
ADAPTER=/opt/sutang-telegram-bridge/examples/faster_whisper_transcriber.py
CONFIG=/etc/sutang-telegram-bridge/config.json
MODEL_REVISION=536b0662742c02347bc0e980a01041f333bce120

test -f "$CONFIG"
id sutang-bridge >/dev/null
install -d -m 0755 -o root -g root /opt/sutang-telegram-bridge/examples
install -m 0755 -o root -g root \
  "$PROJECT_DIR/examples/faster_whisper_transcriber.py" "$ADAPTER"
python3 -m venv "$VOICE_DIR"
"$VOICE_DIR/bin/python" -m pip install --disable-pip-version-check "faster-whisper==1.2.1"
install -d -m 0755 -o root -g root "$MODEL_DIR"
"$VOICE_DIR/bin/python" - "$MODEL_DIR" "$MODEL_REVISION" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="Systran/faster-whisper-small",
    revision=sys.argv[2],
    local_dir=sys.argv[1],
)
PY
chown -R root:root "$VOICE_DIR"
find "$VOICE_DIR" -type d -exec chmod 0755 {} +
find "$VOICE_DIR" -type f -exec chmod u=rw,go=r {} +
find "$VOICE_DIR/bin" -type f -exec chmod 0755 {} +

cp -a "$CONFIG" "$CONFIG.voice-backup"
python3 - "$CONFIG" "$VOICE_DIR/bin/python" "$ADAPTER" "$MODEL_DIR" <<'PY'
import json
import os
import sys
import tempfile

path, python, adapter, model = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data["transcription"] = {
    "command": [python, adapter, "--model", model],
    "timeout_seconds": 180,
    "max_chars": 12000,
    "pass_env": [],
}
directory = os.path.dirname(path)
fd, temp_path = tempfile.mkstemp(prefix="config.", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)
finally:
    if os.path.exists(temp_path):
        os.unlink(temp_path)
PY
chown root:root "$CONFIG"
chmod 0600 "$CONFIG"

runuser -u sutang-bridge -- "$VOICE_DIR/bin/python" - "$MODEL_DIR" <<'PY'
import sys
from faster_whisper import WhisperModel
WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
PY

if systemctl is-active --quiet sutang-telegram-bridge.service; then
  systemctl restart sutang-telegram-bridge.service
  systemctl is-active --quiet sutang-telegram-bridge.service
fi
echo "Local voice transcription is active."
