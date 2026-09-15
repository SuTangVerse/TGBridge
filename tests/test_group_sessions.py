import json
import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.group_sessions import GroupSessionStore


class GroupSessionStoreTests(unittest.TestCase):
    def test_complete_resume_rotate_and_discard(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sessions.json"
            store = GroupSessionStore(path, max_turns=2, max_age_seconds=60)
            empty = store.prepare("a:-10:7", binding="scope-a", now=100)
            self.assertIsNone(empty.session_id)

            store.complete(
                "a:-10:7",
                binding="scope-a",
                previous_session_id=None,
                session_id="thread-1",
                through_context_id=4,
                now=101,
            )
            resumed = store.prepare("a:-10:7", binding="scope-a", now=102)
            self.assertEqual(resumed.session_id, "thread-1")
            self.assertEqual(resumed.through_context_id, 4)
            self.assertFalse(resumed.rotated)

            store.complete(
                "a:-10:7",
                binding="scope-a",
                previous_session_id="thread-1",
                session_id="thread-1",
                through_context_id=8,
                now=103,
            )
            rotated = store.prepare("a:-10:7", binding="scope-a", now=104)
            self.assertIsNone(rotated.session_id)
            self.assertTrue(rotated.rotated)

            store.complete(
                "a:-10:7",
                binding="scope-a",
                previous_session_id=None,
                session_id="thread-2",
                through_context_id=9,
                now=105,
            )
            changed = store.prepare("a:-10:7", binding="scope-b", now=106)
            self.assertIsNone(changed.session_id)
            self.assertTrue(changed.rotated)
            store.discard("a:-10:7")
            self.assertEqual(store.inspect("a:-10:7")["session_id"], "")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_compare_and_swap_does_not_overwrite_newer_session(self):
        with tempfile.TemporaryDirectory() as temp:
            store = GroupSessionStore(Path(temp) / "sessions.json")
            store.complete(
                "a:-10:0", binding="scope", previous_session_id=None,
                session_id="newer", through_context_id=10, now=100,
            )
            store.complete(
                "a:-10:0", binding="scope", previous_session_id="older",
                session_id="stale", through_context_id=99, now=101,
            )
            value = store.inspect("a:-10:0")
            self.assertEqual(value["session_id"], "newer")
            self.assertEqual(value["through_context_id"], 10)

    def test_discard_prefix_clears_public_and_scene_variants_only(self):
        with tempfile.TemporaryDirectory() as temp:
            store = GroupSessionStore(Path(temp) / "sessions.json")
            for key in (
                "a:-10:7:public",
                "a:-10:7:scene:one",
                "a:-10:8:public",
            ):
                store.complete(
                    key,
                    binding="scope",
                    previous_session_id=None,
                    session_id="thread-" + key,
                    through_context_id=1,
                    now=100,
                )
            store.discard_prefix("a:-10:7")

            self.assertEqual(store.inspect("a:-10:7:public")["session_id"], "")
            self.assertEqual(store.inspect("a:-10:7:scene:one")["session_id"], "")
            self.assertNotEqual(store.inspect("a:-10:8:public")["session_id"], "")
