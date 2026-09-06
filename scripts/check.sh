#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
python3 -m compileall -q src examples/echo_agent.py
PYTHONPATH=src python3 -m unittest discover -s tests -v

if grep -RInE '[0-9]{7,12}:[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}' \
  --exclude-dir=.git .; then
  echo "Possible secret detected" >&2
  exit 1
fi

echo "All checks passed."
