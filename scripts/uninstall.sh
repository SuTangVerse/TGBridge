#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ] || [ "${1:-}" != "--yes" ]; then
  echo "Usage: sudo ./scripts/uninstall.sh --yes" >&2
  exit 1
fi

systemctl disable --now sutang-telegram-bridge.service 2>/dev/null || true
rm -f /etc/systemd/system/sutang-telegram-bridge.service
rm -rf /opt/sutang-telegram-bridge
systemctl daemon-reload
echo "Program removed. Configuration and state were preserved."
