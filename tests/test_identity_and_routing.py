import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.bridge import Bridge
from sutang_telegram_bridge.identity import identity_merge_conflict
from sutang_telegram_bridge.models import AgentConfig, BotIdentity, BridgeConfig, IncomingMessage
from sutang_telegram_bridge.store import DeliveryStore


class DummyClient:
    def __init__(self, token):
        self.token = token


class IdentityAndRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = DeliveryStore(root / "db.sqlite3")
        agents = (
            AgentConfig("a", "A_TOKEN", ("/bin/echo",), aliases=("Alpha",)),
            AgentConfig("b", "B_TOKEN", ("/bin/echo",), aliases=("Beta",)),
        )
        config = BridgeConfig(
            agents=agents,
            owner_ids=frozenset({1}),
            allowed_group_ids=frozenset({-10}),
            trusted_group_ids=frozenset({-10}),
            group_modes={-10: "adaptive"},
            default_group_agent="a",
            state_dir=root,
        )
        self.bridge = Bridge(config, {"a": "x", "b": "y"}, self.store, client_factory=DummyClient)
        self.bridge.identities = {"a": BotIdentity(101, "alpha_bot"), "b": BotIdentity(102, "beta_bot")}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def message(self, bot_key="a", sender=2, text="hello", reply=None):
        return IncomingMessage(
            bot_key=bot_key,
            update_id=1,
            chat_id=-10,
            chat_type="supergroup",
            message_id=20,
            thread_id=None,
            sender_id=sender,
            sender_name="Friend",
            sender_username="friend",
            sender_is_bot=False,
            text=text,
            reply_to=reply,
            raw_message={},
        )

    def test_adaptive_routes_mentions_but_not_unaddressed_third_party(self):
        self.assertFalse(self.bridge._should_route(self.message()))
        self.assertTrue(self.bridge._should_route(self.message(text="@alpha_bot help")))

    def test_owner_unaddressed_message_uses_only_default_agent(self):
        self.assertTrue(self.bridge._should_route(self.message(bot_key="a", sender=1)))
        self.assertFalse(self.bridge._should_route(self.message(bot_key="b", sender=1)))

    def test_reply_edge_targets_the_replied_bot(self):
        reply = {"from": {"id": 102}}
        self.assertTrue(self.bridge._should_route(self.message(bot_key="b", reply=reply)))

    def test_known_people_cannot_be_merged_without_evidence(self):
        self.store.remember_participant(-10, 1, "Owner", "owner", True)
        self.store.remember_participant(-10, 2, "FriendB", "friend_b", False)
        self.assertTrue(identity_merge_conflict(self.store, -10, "FriendB 就是 Owner"))
        self.assertFalse(identity_merge_conflict(self.store, -10, "FriendB 正在回复 Owner"))

    def test_dynamic_mode_and_pause_override_static_config(self):
        self.store.set_group_mode(-10, "full")
        self.assertTrue(self.bridge._should_route(self.message(bot_key="b")))
        self.store.set_agent_paused("b", True)
        self.assertFalse(self.bridge._should_route(self.message(bot_key="b", text="@beta_bot help")))
