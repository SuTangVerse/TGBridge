from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from .bridge import Bridge
from .config import load_config
from .store import DeliveryStore


async def _run() -> None:
    config_path = Path(os.environ.get("BRIDGE_CONFIG_PATH", "/etc/sutang-telegram-bridge/config.json"))
    config, tokens = load_config(config_path)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    store = DeliveryStore(config.state_dir / "delivery.sqlite3")
    bridge = Bridge(config, tokens, store)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, bridge.stop)
    try:
        await bridge.run()
    finally:
        store.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("BRIDGE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
