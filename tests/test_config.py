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
        self.assertFalse(config.agents[0].incremental_group_sessions)
        self.assertFalse(config.agents[0].group_scene_consent)
        self.assertEqual(config.group_session_max_turns, 40)

    def test_loads_bounded_incremental_group_session_settings(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"TEST_BOT_TOKEN": "test-token"}
        ):
            path = self._write(
                Path(temp),
                {
                    "group_session_max_turns": 25,
                    "group_session_max_age_seconds": 3600,
                    "agents": [{
                        "key": "a", "token_env": "TEST_BOT_TOKEN",
                        "command": ["/bin/echo"],
                        "incremental_group_sessions": True,
                    }],
                },
            )
            config, _ = load_config(path)
        self.assertTrue(config.agents[0].incremental_group_sessions)
        self.assertEqual(config.group_session_max_turns, 25)
        self.assertEqual(config.group_session_max_age_seconds, 3600)

    def test_rejects_non_boolean_incremental_group_setting(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"TEST_BOT_TOKEN": "test-token"}
        ):
            path = self._write(
                Path(temp),
                {"agents": [{
                    "key": "a", "token_env": "TEST_BOT_TOKEN",
                    "command": ["/bin/echo"],
                    "incremental_group_sessions": "yes",
                }]},
            )
            with self.assertRaisesRegex(ValueError, "must be boolean"):
                load_config(path)

    def test_loads_and_bounds_group_scene_consent_settings(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"TEST_BOT_TOKEN": "test-token"}
        ):
            path = self._write(
                Path(temp),
                {
                    "group_scene_request_ttl_seconds": 120,
                    "group_scene_active_ttl_seconds": 600,
                    "agents": [{
                        "key": "a", "token_env": "TEST_BOT_TOKEN",
                        "command": ["/bin/echo"],
                        "group_scene_consent": True,
                    }],
                },
            )
            config, _ = load_config(path)
        self.assertTrue(config.agents[0].group_scene_consent)
        self.assertEqual(config.group_scene_request_ttl_seconds, 120)
        self.assertEqual(config.group_scene_active_ttl_seconds, 600)

        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"TEST_BOT_TOKEN": "test-token"}
        ):
            with self.assertRaisesRegex(ValueError, "group_scene_active"):
                load_config(
                    self._write(
                        Path(temp), {"group_scene_active_ttl_seconds": 30}
                    )
                )

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
