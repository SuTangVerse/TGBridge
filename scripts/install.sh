#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo ./scripts/install.sh" >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
INSTALL_DIR=/opt/sutang-telegram-bridge
CONFIG_DIR=/etc/sutang-telegram-bridge

if ! id sutang-bridge >/dev/null 2>&1; then
  useradd --system --home /var/lib/sutang-telegram-bridge --shell /usr/sbin/nologin sutang-bridge
fi
groupadd --force sutang-agent-files
usermod -aG sutang-agent-files sutang-bridge

install -d -m 0755 -o root -g root "$INSTALL_DIR" "$INSTALL_DIR/src" "$INSTALL_DIR/examples"
cp -a "$PROJECT_DIR/src/sutang_telegram_bridge" "$INSTALL_DIR/src/"
install -m 0755 -o root -g root "$PROJECT_DIR/examples/echo_agent.py" "$INSTALL_DIR/examples/echo_agent.py"
install -m 0755 -o root -g root "$PROJECT_DIR/examples/faster_whisper_transcriber.py" "$INSTALL_DIR/examples/faster_whisper_transcriber.py"
install -d -m 0700 -o root -g root "$CONFIG_DIR"
if [ ! -e "$CONFIG_DIR/bridge.env" ]; then
  install -m 0600 -o root -g root "$PROJECT_DIR/examples/bridge.env.example" "$CONFIG_DIR/bridge.env"
fi
if [ ! -e "$CONFIG_DIR/config.json" ]; then
  install -m 0600 -o root -g root "$PROJECT_DIR/examples/config.production.json" "$CONFIG_DIR/config.json"
fi
install -m 0644 -o root -g root "$PROJECT_DIR/examples/agent-bridge.service" /etc/systemd/system/sutang-telegram-bridge.service
install -d -m 0711 -o sutang-bridge -g sutang-bridge /var/lib/sutang-telegram-bridge
systemctl daemon-reload

echo "Installed. Fill $CONFIG_DIR/bridge.env and config.json, install fixed agent runners, then run:"
echo "sudo systemctl enable --now sutang-telegram-bridge"
