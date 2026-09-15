import asyncio
import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.bridge import Bridge
from sutang_telegram_bridge.models import AgentConfig, BotIdentity, BridgeConfig
from sutang_telegram_bridge.runner import AgentOutput, SessionResumeError
from sutang_telegram_bridge.store import DeliveryStore


class FakeClient:
    def __init__(self, token):
        self.texts = []
        self.fail_text = False

    async def send_action(self, chat_id, thread_id):
        return None

    async def send_text(self, chat_id, text, thread_id, reply_to, reply_markup=None):
        if self.fail_text:
            raise RuntimeError("synthetic delivery failure")
        self.texts.append((chat_id, text, thread_id, reply_to))

    async def set_reaction(self, chat_id, message_id, emoji):
        return None

    async def send_media(self, *args):
        return None


class SessionRunner:
    def __init__(self):
        self.calls = []
        self.reject_next_resume = False

    async def run(self, agent, prompt, private, timeout, *, session_id=None):
        self.calls.append((session_id, prompt, private))
        if session_id and self.reject_next_resume:
            self.reject_next_resume = False
            raise SessionResumeError("synthetic stale session")
        return AgentOutput(
            f"answer-{len(self.calls)}",
            session_id=session_id or f"thread-{len(self.calls)}",
        )


class IncrementalGroupSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        agent = AgentConfig(
            "a", "A_TOKEN", ("/bin/echo",), aliases=("Alpha",),
            group_cwd=root, incremental_group_sessions=True,
        )
        config = BridgeConfig(
            agents=(agent,), owner_ids=frozenset({1}),
            allowed_group_ids=frozenset({-10}),
            trusted_group_ids=frozenset({-10}),
            group_modes={-10: "adaptive"}, default_group_agent="a",
            state_dir=root,
        )
        self.store = DeliveryStore(root / "bridge.sqlite3")
        self.runner = SessionRunner()
        self.bridge = Bridge(
            config, {"a": "token"}, self.store, self.runner, FakeClient
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
    def update(update_id, text, *, sender=1, thread=7):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "message_thread_id": thread,
                "chat": {"id": -10, "type": "supergroup", "title": "Room"},
                "from": {
                    "id": sender, "first_name": f"User {sender}", "is_bot": False
                },
                "text": text,
            },
        }

    async def ingest(self, update):
        await self.bridge.ingest("a", update)
        await asyncio.gather(*tuple(self.bridge._tasks))

    async def test_resume_uses_only_delta_and_keeps_topic_isolated(self):
        await self.ingest(self.update(1, "@alpha_bot first"))
        self.assertIsNone(self.runner.calls[0][0])
        self.assertEqual(
            self.bridge.group_sessions.inspect("a:-10:7")["session_id"],
            "thread-1",
        )

        await self.ingest(self.update(2, "side detail", sender=2))
        self.assertEqual(len(self.runner.calls), 1)
        await self.ingest(self.update(3, "@alpha_bot follow up"))
        self.assertEqual(self.runner.calls[1][0], "thread-1")
        self.assertIn("Incremental same-agent", self.runner.calls[1][1])
        self.assertIn("side detail", self.runner.calls[1][1])
        self.assertNotIn("@alpha_bot first", self.runner.calls[1][1])

        await self.ingest(self.update(4, "@alpha_bot other topic", thread=8))
        self.assertIsNone(self.runner.calls[2][0])
        self.assertEqual(
            self.bridge.group_sessions.inspect("a:-10:8")["session_id"],
            "thread-3",
        )

    async def test_resume_rejection_retries_once_with_full_context(self):
        await self.ingest(self.update(10, "@alpha_bot first"))
        self.runner.reject_next_resume = True
        await self.ingest(self.update(11, "@alpha_bot second"))
        self.assertEqual([item[0] for item in self.runner.calls], [None, "thread-1", None])
        self.assertIn("Recent same-agent", self.runner.calls[-1][1])
        self.assertEqual(
            self.bridge.group_sessions.inspect("a:-10:7")["session_id"],
            "thread-3",
        )

    async def test_session_cursor_waits_for_telegram_delivery(self):
        self.client.fail_text = True
        await self.ingest(self.update(20, "@alpha_bot first"))
        self.assertEqual(
            self.bridge.group_sessions.inspect("a:-10:7")["session_id"], ""
        )
        row = self.store.get_update("a", 20)
        self.assertEqual(row["state"], "generated")

        self.client.fail_text = False
        await self.bridge._deliver_cached(row)
        self.assertEqual(
            self.bridge.group_sessions.inspect("a:-10:7")["session_id"],
            "thread-1",
        )
        self.assertEqual(self.store.get_update("a", 20)["state"], "done")
