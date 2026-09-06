import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sutang_telegram_bridge.config import load_config


class ConfigTests(unittest.TestCase):
    def _write(self, root: Path, overrides=None) -> Path:
        data = {
            "owner_ids": [1],
            "allowed_group_ids": [-10],
            "trusted_group_ids": [-10],
            "default_group_agent": "a",
            "state_dir": str(root / "state"),
            "agents": [
                {
                    "key": "a",
                    "token_env": "TEST_BOT_TOKEN",
                    "command": ["/bin/echo"],
                }
            ],
        }
        data.update(overrides or {})
        path = root / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_loads_token_from_environment_not_json(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_BOT_TOKEN": "test-token"}):
            config, tokens = load_config(self._write(Path(temp)))
        self.assertEqual(tokens, {"a": "test-token"})
        self.assertEqual(config.default_group_agent, "a")
        self.assertEqual(config.bot_pair_call_limit, 4)
        self.assertEqual(config.bot_pair_window_seconds, 120)
        self.assertEqual(config.group_bot_call_limit, 8)

    def test_rejects_relative_executable(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_BOT_TOKEN": "x"}):
            path = self._write(
                Path(temp),
                {"agents": [{"key": "a", "token_env": "TEST_BOT_TOKEN", "command": ["python3"]}]},
            )
            with self.assertRaisesRegex(ValueError, "absolute"):
                load_config(path)

    def test_trusted_groups_must_be_allowed(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_BOT_TOKEN": "x"}):
            with self.assertRaisesRegex(ValueError, "subset"):
                load_config(self._write(Path(temp), {"trusted_group_ids": [-99]}))

    def test_rejects_unbounded_bot_pair_settings(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"TEST_BOT_TOKEN": "x"}
        ):
            with self.assertRaisesRegex(ValueError, "bot_pair_call_limit"):
                load_config(
                    self._write(Path(temp), {"bot_pair_call_limit": 21})
                )
            with self.assertRaisesRegex(ValueError, "bot_pair_window_seconds"):
                load_config(
                    self._write(Path(temp), {"bot_pair_window_seconds": 0})
                )
            with self.assertRaisesRegex(ValueError, "group_bot_call_limit"):
                load_config(
                    self._write(Path(temp), {"group_bot_call_limit": 101})
                )
