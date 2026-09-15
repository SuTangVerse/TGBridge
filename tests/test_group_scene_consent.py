import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from sutang_telegram_bridge.bridge import Bridge
from sutang_telegram_bridge.group_scene import (
    extract_group_scene_signal,
    strip_group_scene_signal,
)
from sutang_telegram_bridge.models import AgentConfig, BotIdentity, BridgeConfig
from sutang_telegram_bridge.store import DeliveryStore


class FakeClient:
    def __init__(self, token):
        self.texts = []
        self.markups = []
        self.callback_answers = []
        self.cleared_markups = []

    async def send_action(self, chat_id, thread_id):
        pass

    async def send_text(self, chat_id, text, thread_id, reply_to, reply_markup=None):
        self.texts.append((chat_id, text, thread_id, reply_to))
        self.markups.append(reply_markup)

    async def answer_callback(self, callback_query_id, text):
        self.callback_answers.append((callback_query_id, text))

    async def clear_reply_markup(self, chat_id, message_id):
        self.cleared_markups.append((chat_id, message_id))

    async def set_reaction(self, chat_id, message_id, emoji):
        pass

    async def send_media(self, *args):
        pass

    async def download(self, file_id, destination, max_bytes):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"attachment")


class SequenceRunner:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []
        self.private_flags = []

    async def run(self, agent, prompt, private, timeout):
        self.prompts.append(prompt)
        self.private_flags.append(private)
        await asyncio.sleep(0)
        return self.answers.pop(0)


class GroupSceneSignalTests(unittest.TestCase):
    def test_hidden_signal_is_stripped_and_validated(self):
        visible, signal = extract_group_scene_signal(
            'NO_REPLY<telegram_group_scene_request>{"summary":"private roleplay"}'
            "</telegram_group_scene_request>"
        )
        self.assertEqual(visible, "NO_REPLY")
        self.assertEqual(signal.summary, "private roleplay")

    def test_missing_summary_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_group_scene_signal(
                "<telegram_group_scene_request>{}</telegram_group_scene_request>"
            )

    def test_malformed_or_stray_control_tags_do_not_leak(self):
        self.assertEqual(
            strip_group_scene_signal(
                "visible<telegram_group_scene_request>{bad json"
            ),
            "visible",
        )
        self.assertEqual(
            strip_group_scene_signal("visible</telegram_group_scene_request>"),
            "visible",
        )


class GroupSceneStoreTests(unittest.TestCase):
    def test_consent_is_owner_scope_bound_idempotent_and_expiring(self):
        with tempfile.TemporaryDirectory() as temp:
            store = DeliveryStore(Path(temp) / "db.sqlite3")
            now = 1000.0
            row, created = store.create_group_scene_request(
                request_key="a:-10:7:1:90",
                bot_key="a",
                chat_id=-10,
                thread_id=7,
                owner_id=1,
                source_update_id=80,
                source_message_id=90,
                chat_title="Test",
                sender_name="Owner",
                sender_username="owner",
                source_text="request",
                reply_to=None,
                raw_message={},
                summary="private scene",
                ttl_seconds=300,
                now=now,
            )
            duplicate, duplicate_created = store.create_group_scene_request(
                request_key="a:-10:7:1:90",
                bot_key="a",
                chat_id=-10,
                thread_id=7,
                owner_id=1,
                source_update_id=80,
                source_message_id=90,
                chat_title="Test",
                sender_name="Owner",
                sender_username="owner",
                source_text="request",
                reply_to=None,
                raw_message={},
                summary="private scene",
                ttl_seconds=300,
                now=now,
            )
            wrong_owner = store.decide_group_scene(
                str(row["scene_id"]),
                "allow",
                bot_key="a",
                owner_id=2,
                update_id=91,
                active_ttl_seconds=900,
                now=now + 1,
            )
            allowed = store.decide_group_scene(
                str(row["scene_id"]),
                "allow",
                bot_key="a",
                owner_id=1,
                update_id=91,
                active_ttl_seconds=10,
                now=now + 1,
            )
            replay = store.decide_group_scene(
                str(row["scene_id"]),
                "allow",
                bot_key="a",
                owner_id=1,
                update_id=91,
                active_ttl_seconds=10,
                now=now + 2,
            )
            other_update = store.decide_group_scene(
                str(row["scene_id"]),
                "allow",
                bot_key="a",
                owner_id=1,
                update_id=92,
                active_ttl_seconds=10,
                now=now + 2,
            )
            active = store.active_group_scene("a", -10, 7, 1, now=now + 2)
            wrong_topic = store.active_group_scene("a", -10, 8, 1, now=now + 2)
            expired = store.expire_group_scenes("a", -10, 7, now=now + 20)
            store.close()

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate["scene_id"], row["scene_id"])
        self.assertEqual(wrong_owner["status"], "unknown")
        self.assertEqual(allowed["status"], "activated")
        self.assertEqual(replay["status"], "replay")
        self.assertEqual(other_update["status"], "already")
        self.assertIsNotNone(active)
        self.assertIsNone(wrong_topic)
        self.assertTrue(expired)


class GroupSceneBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        agent = AgentConfig(
            "a",
            "A_TOKEN",
            ("/bin/echo",),
            aliases=("Alpha",),
            media_root=root,
            group_scene_consent=True,
        )
        config = BridgeConfig(
            agents=(agent,),
            owner_ids=frozenset({1}),
            allowed_group_ids=frozenset({-10, -20}),
            trusted_group_ids=frozenset({-10}),
            group_modes={-10: "full", -20: "full"},
            default_group_agent="a",
            state_dir=root,
        )
        self.store = DeliveryStore(root / "db.sqlite3")
        self.runner = SequenceRunner()
        self.bridge = Bridge(
            config,
            {"a": "token"},
            self.store,
            self.runner,
            FakeClient,
        )
        self.bridge.identities = {"a": BotIdentity(101, "alpha_bot")}
        self.client = self.bridge.clients["a"]

    async def asyncTearDown(self):
        for task in tuple(self.bridge._tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.bridge._tasks), return_exceptions=True)
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def group_update(update_id, text, *, chat_id=-10, sender_id=1, thread_id=7):
        message = {
            "message_id": update_id + 100,
            "message_thread_id": thread_id,
            "chat": {"id": chat_id, "type": "supergroup", "title": "Test Group"},
            "from": {
                "id": sender_id,
                "first_name": "Owner" if sender_id == 1 else "Guest",
                "is_bot": False,
            },
            "text": text,
        }
        return {"update_id": update_id, "message": message}

    @staticmethod
    def callback_update(update_id, callback_data):
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"cb-{update_id}",
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "data": callback_data,
                "message": {
                    "message_id": update_id + 200,
                    "chat": {"id": 1, "type": "private"},
                    "text": "confirmation",
                },
            },
        }

    async def ingest(self, update):
        await self.bridge.ingest("a", update)
        await asyncio.gather(*tuple(self.bridge._tasks))

    async def test_natural_request_requires_dm_then_replays_exact_group_turn(self):
        self.runner.answers.extend(
            [
                'NO_REPLY<telegram_group_scene_request>{"summary":"intimate roleplay"}'
                "</telegram_group_scene_request>",
                "authorized scene reply",
                "continued scene reply",
            ]
        )
        await self.ingest(self.group_update(1, "Alpha, begin the private scene"))

        self.assertFalse(any(item[0] == -10 for item in self.client.texts))
        self.assertEqual(self.client.texts[-1][0], 1)
        markup = self.client.markups[-1]
        allow_data = markup["inline_keyboard"][0][0]["callback_data"]
        self.assertRegex(allow_data, r"^gsc:[0-9a-f]{16}:allow$")
        self.assertNotIn("Server-verified group scene consent", self.runner.prompts[0])

        await self.ingest(self.callback_update(2, allow_data))

        group_texts = [item[1] for item in self.client.texts if item[0] == -10]
        self.assertEqual(group_texts, ["authorized scene reply"])
        self.assertIn("Server-verified group scene consent", self.runner.prompts[1])
        self.assertIn('"text": "Alpha, begin the private scene"', self.runner.prompts[1])
        self.assertFalse(self.runner.private_flags[1])
        self.assertEqual(self.client.texts[-1][0], 1)
        close_data = self.client.markups[-1]["inline_keyboard"][0][0]["callback_data"]
        self.assertTrue(close_data.endswith(":close"))

        await self.ingest(self.group_update(3, "continue"))
        self.assertIn("Server-verified group scene consent", self.runner.prompts[2])
        self.assertEqual(
            [item[1] for item in self.client.texts if item[0] == -10][-1],
            "continued scene reply",
        )

        await self.ingest(self.group_update(4, "/scene_close"))
        self.assertIsNone(self.store.active_group_scene("a", -10, 7, 1))
        self.assertEqual(self.store.get_context("a", -10, 7, 24), [])

    async def test_explicit_command_is_deterministic_and_redacts_dm_excerpt(self):
        await self.ingest(
            self.group_update(
                10,
                "/scene_open private URL https://private.example/x api_key=abcdefghijklmnop",
            )
        )
        self.assertEqual(self.runner.prompts, [])
        notice = self.client.texts[-1][1]
        self.assertIn("[URL omitted]", notice)
        self.assertNotIn("abcdefghijklmnop", notice)

    async def test_non_owner_and_external_group_cannot_open_scene(self):
        marker = (
            'NO_REPLY<telegram_group_scene_request>{"summary":"private roleplay"}'
            "</telegram_group_scene_request>"
        )
        self.runner.answers.extend([marker, marker])
        await self.ingest(
            self.group_update(20, "Alpha do it", sender_id=2)
        )
        self.assertIn("current sender is not an Owner", self.runner.prompts[0])
        await self.ingest(
            self.group_update(21, "Alpha do it", chat_id=-20)
        )
        self.assertFalse(any(item[0] == 1 for item in self.client.texts))

    async def test_expired_scene_clears_prior_topic_context_before_next_turn(self):
        old = time.time() - 100
        row, _ = self.store.create_group_scene_request(
            request_key="expired",
            bot_key="a",
            chat_id=-10,
            thread_id=7,
            owner_id=1,
            source_update_id=30,
            source_message_id=130,
            chat_title="Test Group",
            sender_name="Owner",
            sender_username="",
            source_text="request",
            reply_to=None,
            raw_message={},
            summary="scene",
            ttl_seconds=300,
            now=old,
        )
        self.store.decide_group_scene(
            str(row["scene_id"]),
            "allow",
            bot_key="a",
            owner_id=1,
            update_id=31,
            active_ttl_seconds=10,
            now=old + 1,
        )
        self.store.add_context(
            "a", -10, 7, "assistant", {"agent_key": "a"},
            "sensitive old scene context", 24,
        )
        self.runner.answers.append("ordinary reply")

        await self.ingest(self.group_update(32, "Alpha, normal question"))

        self.assertNotIn("sensitive old scene context", self.runner.prompts[-1])
        self.assertNotIn("Server-verified group scene consent", self.runner.prompts[-1])
        self.assertIsNone(self.store.active_group_scene("a", -10, 7, 1))


if __name__ == "__main__":
    unittest.main()
