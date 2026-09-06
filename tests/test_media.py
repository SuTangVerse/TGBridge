import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.media import (
    extract_media_control,
    extract_reaction_control,
    split_text,
    validate_media_items,
)
from sutang_telegram_bridge.models import AgentConfig
from sutang_telegram_bridge.store import DeliveryStore


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.media_root = root / "media"
        self.media_root.mkdir()
        self.store = DeliveryStore(root / "db.sqlite3")
        self.agent = AgentConfig("a", "TOKEN", ("/bin/echo",), media_root=self.media_root)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_hidden_control_is_removed(self):
        text, items = extract_media_control(
            'hello<telegram_media>{"items":[{"kind":"sticker","asset_id":"tg_x"}]}</telegram_media>'
        )
        self.assertEqual(text, "hello")
        self.assertEqual(items[0]["kind"], "sticker")

    def test_reaction_control_is_removed_and_validated(self):
        text, emoji = extract_reaction_control(
            'hello<telegram_reaction>{"emoji":"👀"}</telegram_reaction>'
        )
        self.assertEqual(text, "hello")
        self.assertEqual(emoji, "👀")

    def test_local_media_must_stay_under_root(self):
        outside = Path(self.temp.name) / "outside.gif"
        outside.write_bytes(b"GIF89a")
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_media_items(
                [{"kind": "animation", "path": str(outside)}],
                self.agent,
                self.store,
                "a",
                1,
                True,
            )

    def test_same_chat_asset_is_accepted(self):
        asset = self.store.register_asset("a", 1, "sticker", "file-id")
        result = validate_media_items(
            [{"kind": "sticker", "asset_id": asset}], self.agent, self.store, "a", 1, False
        )
        self.assertEqual(result[0]["source"], "file-id")

    def test_text_is_split_below_limit(self):
        chunks = split_text("a" * 31, limit=10)
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 10 for chunk in chunks))
        self.assertEqual("".join(chunks), "a" * 31)
