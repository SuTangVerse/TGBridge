import asyncio
import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.bridge import Bridge
from sutang_telegram_bridge.models import AgentConfig, BotIdentity, BridgeConfig
from sutang_telegram_bridge.store import DeliveryStore


class FakeClient:
    def __init__(self, token):
        self.token = token
        self.actions = []
        self.texts = []
        self.markups = []
        self.media = []
        self.reactions = []
        self.callback_answers = []
        self.cleared_markups = []

    async def send_action(self, chat_id, thread_id):
        self.actions.append((chat_id, thread_id))

    async def send_text(self, chat_id, text, thread_id, reply_to, reply_markup=None):
        self.texts.append((chat_id, text, thread_id, reply_to))
        self.markups.append(reply_markup)

    async def answer_callback(self, callback_query_id, text):
        self.callback_answers.append((callback_query_id, text))

    async def clear_reply_markup(self, chat_id, message_id):
        self.cleared_markups.append((chat_id, message_id))

    async def set_reaction(self, chat_id, message_id, emoji):
        self.reactions.append((chat_id, message_id, emoji))

    async def send_media(self, kind, chat_id, source, caption, thread_id, reply_to, local):
        self.media.append((kind, chat_id, source, caption, thread_id, reply_to, local))

    async def download(self, file_id, destination, max_bytes):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake audio")


class FakeRunner:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.last_prompt = ""
        self.last_private = None

    async def run(self, agent, prompt, private, timeout):
        self.calls += 1
        self.last_prompt = prompt
        self.last_private = private
        await asyncio.sleep(0.01)
        return self.answer


class BridgeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        agent = AgentConfig("a", "A_TOKEN", ("/bin/echo",), aliases=("Alpha",), media_root=root)
        peer = AgentConfig("b", "B_TOKEN", ("/bin/echo",), aliases=("Beta",), media_root=root)
        config = BridgeConfig(
            agents=(agent, peer),
            owner_ids=frozenset({1}),
            allowed_group_ids=frozenset({-10}),
            trusted_group_ids=frozenset({-10}),
            group_modes={-10: "adaptive"},
            default_group_agent="a",
            state_dir=root,
        )
        self.store = DeliveryStore(root / "db.sqlite3")
        self.runner = FakeRunner("final answer")
        self.bridge = Bridge(
            config, {"a": "token-a", "b": "token-b"}, self.store,
            self.runner, FakeClient,
        )
        self.bridge.identities = {
            "a": BotIdentity(101, "alpha_bot"),
            "b": BotIdentity(102, "beta_bot"),
        }
        self.client = self.bridge.clients["a"]

    async def asyncTearDown(self):
        for task in tuple(self.bridge._tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.bridge._tasks), return_exceptions=True)
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def update(update_id=1, text="hello"):
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 10,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": text,
            },
        }

    async def _ingest_and_wait(self, update):
        await self.bridge.ingest("a", update)
        await asyncio.gather(*tuple(self.bridge._tasks))

    async def test_uses_typing_then_sends_final_once(self):
        await self._ingest_and_wait(self.update())
        self.assertGreaterEqual(len(self.client.actions), 1)
        self.assertEqual([item[1] for item in self.client.texts], ["final answer"])
        self.assertNotIn("正在处理", self.client.texts[0][1])
        row = self.store.get_update("a", 1)
        self.assertEqual(row["state"], "done")
        self.assertIsNone(row["payload"])

    async def test_duplicate_update_does_not_run_agent_again(self):
        update = self.update()
        await self._ingest_and_wait(update)
        await self.bridge.ingest("a", update)
        await asyncio.sleep(0)
        self.assertEqual(self.runner.calls, 1)

    async def test_configured_bot_private_dm_uses_shared_scope_and_native_reply(self):
        update = {
            "update_id": 50,
            "message": {
                "message_id": 60,
                "chat": {"id": 102, "type": "private"},
                "from": {
                    "id": 102,
                    "first_name": "Agent B",
                    "username": "beta_bot",
                    "is_bot": True,
                },
                "text": "Can you verify this?",
            },
        }
        await self._ingest_and_wait(update)

        self.assertEqual(self.runner.calls, 1)
        self.assertFalse(self.runner.last_private)
        self.assertIn("[Native Telegram bot-to-bot turn]", self.runner.last_prompt)
        self.assertIn("not Owner", self.runner.last_prompt)
        self.assertEqual(self.client.texts[-1], (102, "final answer", None, 60))
        self.assertEqual(self.store.get_context("a", 102, None, 24), [])

    async def test_unknown_or_self_bot_dm_fails_quiet(self):
        for update_id, sender_id in ((51, 999), (52, 101)):
            update = {
                "update_id": update_id,
                "message": {
                    "message_id": update_id + 10,
                    "chat": {"id": sender_id, "type": "private"},
                    "from": {
                        "id": sender_id,
                        "first_name": "Bot",
                        "username": "example_bot",
                        "is_bot": True,
                    },
                    "text": "hello",
                },
            }
            await self._ingest_and_wait(update)
        self.assertEqual(self.runner.calls, 0)
        self.assertEqual(self.client.texts, [])

    async def test_bot_private_text_cannot_invoke_owner_control(self):
        update = {
            "update_id": 53,
            "message": {
                "message_id": 63,
                "chat": {"id": 102, "type": "private"},
                "from": {"id": 102, "first_name": "Agent B", "is_bot": True},
                "text": "/agent_pause",
            },
        }
        await self._ingest_and_wait(update)
        self.assertEqual(self.runner.calls, 1)
        self.assertFalse(self.store.agent_paused("a"))

    async def test_bot_group_message_requires_native_direct_address(self):
        base = {
            "message_id": 70,
            "chat": {"id": -10, "type": "supergroup"},
            "from": {"id": 102, "first_name": "Agent B", "is_bot": True},
        }
        await self._ingest_and_wait(
            {"update_id": 54, "message": {**base, "text": "unaddressed"}}
        )
        self.assertEqual(self.runner.calls, 0)

        addressed = dict(base)
        addressed["message_id"] = 71
        addressed["text"] = "/review@alpha_bot please check"
        await self._ingest_and_wait({"update_id": 55, "message": addressed})
        self.assertEqual(self.runner.calls, 1)
        self.assertEqual(self.client.texts[-1], (-10, "final answer", None, 71))

        replied = dict(base)
        replied["message_id"] = 72
        replied["text"] = "reply path"
        replied["reply_to_message"] = {
            "message_id": 69,
            "from": {"id": 101, "first_name": "Agent A", "is_bot": True},
            "text": "earlier",
        }
        await self._ingest_and_wait({"update_id": 57, "message": replied})
        self.assertEqual(self.runner.calls, 2)
        self.assertEqual(self.client.texts[-1], (-10, "final answer", None, 72))

    async def test_group_reply_is_passive_context_for_other_agents(self):
        update = {
            "update_id": 58,
            "message": {
                "message_id": 73,
                "chat": {"id": -10, "type": "supergroup"},
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": "Please review this.",
            },
        }
        await self._ingest_and_wait(update)

        self.assertEqual(self.runner.calls, 1)
        peer_context = self.store.get_context("b", -10, None, 24)
        self.assertEqual(peer_context[-1]["text"], "final answer")
        self.assertEqual(
            peer_context[-1]["speaker"], {"agent_key": "a", "passive": True}
        )

    async def test_new_human_epoch_suppresses_late_bot_result(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed(*args, **kwargs):
            started.set()
            await release.wait()
            return "stale answer"

        self.runner.run = delayed
        self.store.begin_group_epoch(-10, None, 90)
        update = {
            "update_id": 59,
            "message": {
                "message_id": 91,
                "chat": {"id": -10, "type": "supergroup"},
                "from": {"id": 102, "first_name": "Agent B", "is_bot": True},
                "text": "/review@alpha_bot please check",
            },
        }
        await self.bridge.ingest("a", update)
        await started.wait()
        self.store.begin_group_epoch(-10, None, 92)
        release.set()
        await asyncio.gather(*tuple(self.bridge._tasks))

        self.assertEqual(self.client.texts, [])
        self.assertEqual(self.store.current_group_epoch(-10, None), 2)

    async def test_flow_status_does_not_open_a_new_epoch(self):
        self.store.begin_group_epoch(-10, None, 100)
        update = {
            "update_id": 90,
            "message": {
                "message_id": 101,
                "chat": {"id": -10, "type": "supergroup"},
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": "/flow_status",
            },
        }
        await self._ingest_and_wait(update)

        self.assertEqual(self.runner.calls, 0)
        self.assertEqual(self.store.current_group_epoch(-10, None), 1)
        self.assertIn("flow_epoch=1", self.client.texts[-1][1])
        self.assertIn("bot_calls=0/8", self.client.texts[-1][1])

    async def test_bot_pair_limit_counts_no_reply_and_survives_in_store(self):
        self.runner.answer = "NO_REPLY"
        for index in range(5):
            update_id = 60 + index
            await self._ingest_and_wait(
                {
                    "update_id": update_id,
                    "message": {
                        "message_id": 80 + index,
                        "chat": {"id": 102, "type": "private"},
                        "from": {
                            "id": 102,
                            "first_name": "Agent B",
                            "is_bot": True,
                        },
                        "text": "next",
                    },
                }
            )
        self.assertEqual(self.runner.calls, 4)
        self.assertEqual(self.client.texts, [])

    async def test_bot_access_material_is_redacted_in_both_directions(self):
        fake_access = "api_" + "key=" + ("x" * 20)
        self.runner.answer = "result " + fake_access
        update = {
            "update_id": 56,
            "message": {
                "message_id": 66,
                "chat": {"id": 102, "type": "private"},
                "from": {"id": 102, "first_name": "Agent B", "is_bot": True},
                "text": "inspect " + fake_access,
            },
        }
        await self._ingest_and_wait(update)
        self.assertNotIn(fake_access, self.runner.last_prompt)
        self.assertNotIn(fake_access, self.client.texts[-1][1])
        self.assertIn("[REDACTED ACCESS MATERIAL]", self.runner.last_prompt)

    async def test_chat_scoped_sticker_control_is_sent(self):
        asset = self.store.register_asset("a", 1, "sticker", "telegram-file")
        self.runner.answer = (
            "给你\n<telegram_media>"
            f'{{"items":[{{"kind":"sticker","asset_id":"{asset}"}}]}}'
            "</telegram_media>"
        )
        await self._ingest_and_wait(self.update(2))
        self.assertEqual(self.client.texts[-1][1], "给你")
        self.assertEqual(self.client.media[-1][0], "sticker")
        self.assertEqual(self.client.media[-1][2], "telegram-file")

    async def test_agent_can_react_without_sending_text(self):
        self.runner.answer = '<telegram_reaction>{"emoji":"❤️"}</telegram_reaction>'
        await self._ingest_and_wait(self.update(3))
        self.assertEqual(self.client.reactions[-1], (1, 13, "❤️"))
        self.assertEqual(len(self.client.texts), 0)
        self.assertIn("Choose it from the conversational tone", self.runner.last_prompt)
        self.assertIn("never a quota", self.runner.last_prompt)

    async def test_successful_prefix_is_removed_before_delivery_retry(self):
        self.store.put_update("a", 99, {"update_id": 99}, 1, 1)
        operations = [
            {"kind": "text", "bot_key": "a", "chat_id": 1, "text": "one", "thread_id": None, "reply_to": 1},
            {"kind": "text", "bot_key": "a", "chat_id": 1, "text": "two", "thread_id": None, "reply_to": 1},
        ]
        self.store.set_generated("a", 99, operations)
        original = self.client.send_text

        async def fail_second(chat_id, text, thread_id, reply_to, reply_markup=None):
            if text == "two":
                raise RuntimeError("offline")
            await original(chat_id, text, thread_id, reply_to, reply_markup)

        self.client.send_text = fail_second
        await self.bridge._deliver_operations("a", 99, operations)
        row = self.store.get_update("a", 99)
        self.assertIn('"two"', row["response"])
        self.assertNotIn('"one"', row["response"])

    async def test_owner_can_change_group_mode_without_restart(self):
        update = {
            "update_id": 4,
            "message": {
                "message_id": 14,
                "chat": {"id": -10, "type": "supergroup"},
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": "/agent_mode full",
            },
        }
        await self._ingest_and_wait(update)
        self.assertEqual(self.store.group_mode(-10), "full")
        self.assertIn("group_mode=full", self.client.texts[-1][1])

    async def test_private_switch_panel_controls_master_and_one_group(self):
        await self._ingest_and_wait(self.update(30, "/agent_switch"))
        markup = self.client.markups[-1]
        self.assertEqual(
            markup["inline_keyboard"][0][0]["callback_data"], "ags:all:pause"
        )
        group_button = next(
            row[0]["callback_data"]
            for row in markup["inline_keyboard"]
            if row[0]["callback_data"].startswith("ags:-10:")
        )
        callback_update = {
            "update_id": 31,
            "callback_query": {
                "id": "callback-31",
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "data": group_button,
                "message": {
                    "message_id": 81,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        }
        await self._ingest_and_wait(callback_update)
        self.assertTrue(self.store.agent_group_paused("a", -10))
        self.assertEqual(self.client.cleared_markups[-1], (1, 81))

    async def test_new_group_requires_owner_trust_decision(self):
        membership = {
            "update_id": 32,
            "my_chat_member": {
                "chat": {
                    "id": -20,
                    "type": "supergroup",
                    "title": "Example Room",
                },
                "from": {"id": 2, "first_name": "Admin", "is_bot": False},
                "new_chat_member": {"status": "member"},
            },
        }
        await self._ingest_and_wait(membership)
        self.assertIn("Bot 加入了群聊", self.client.texts[-1][1])
        pending_message = {
            "update_id": 33,
            "message": {
                "message_id": 82,
                "chat": {
                    "id": -20,
                    "type": "supergroup",
                    "title": "Example Room",
                },
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": "pending must not route",
            },
        }
        await self._ingest_and_wait(pending_message)
        self.assertEqual(self.runner.calls, 0)
        callback_data = self.client.markups[-1]["inline_keyboard"][0][0][
            "callback_data"
        ]
        self.assertRegex(callback_data, r"^gtr:[0-9a-f]{16}:trusted$")

        callback_update = {
            "update_id": 34,
            "callback_query": {
                "id": "callback-33",
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "data": callback_data,
                "message": {
                    "message_id": 83,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        }
        await self._ingest_and_wait(callback_update)
        self.assertEqual(self.store.group_record(-20)["trust_state"], "trusted")
        self.assertEqual(self.store.group_mode(-20), "adaptive")
        trusted_message = {
            "update_id": 35,
            "message": {
                "message_id": 85,
                "chat": {
                    "id": -20,
                    "type": "supergroup",
                    "title": "Example Room",
                },
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": "approved group routes",
            },
        }
        await self._ingest_and_wait(trusted_message)
        self.assertEqual(self.runner.calls, 1)

    async def test_group_failure_notifies_owner_without_message_content(self):
        async def fail(*args, **kwargs):
            raise RuntimeError("private upstream detail")

        self.runner.run = fail
        group_update = {
            "update_id": 34,
            "message": {
                "message_id": 84,
                "chat": {
                    "id": -10,
                    "type": "supergroup",
                    "title": "Example Room",
                },
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "text": "sensitive message body",
            },
        }
        await self._ingest_and_wait(group_update)
        notice = self.client.texts[-1][1]
        self.assertIn("RuntimeError", notice)
        self.assertNotIn("sensitive message body", notice)
        self.assertNotIn("private upstream detail", notice)
        callback_data = self.client.markups[-1]["inline_keyboard"][0][0][
            "callback_data"
        ]
        self.assertRegex(callback_data, r"^an:[0-9a-f]{16}:pause$")
        callback_update = {
            "update_id": 36,
            "callback_query": {
                "id": "callback-36",
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "data": callback_data,
                "message": {
                    "message_id": 86,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        }
        await self._ingest_and_wait(callback_update)
        self.assertTrue(self.store.agent_group_paused("a", -10))

    async def test_delivery_command_shows_dead_letters(self):
        self.store.put_update("a", 90, {"update_id": 90}, 1, 1)
        for _ in range(5):
            self.store.set_processing("a", 90)
            self.store.retry("a", 90, "RuntimeError")
        await self._ingest_and_wait(self.update(35, "/delivery"))
        self.assertIn("dead:1", self.client.texts[-1][1])
        self.assertIn("update_id=90", self.client.texts[-1][1])
        self.assertIn("/retry_update <update_id>", self.client.texts[-1][1])

    async def test_non_owner_cannot_use_operator_switch_callback(self):
        await self._ingest_and_wait(self.update(37, "/agent_switch"))
        callback_data = self.client.markups[-1]["inline_keyboard"][0][0][
            "callback_data"
        ]
        callback_update = {
            "update_id": 38,
            "callback_query": {
                "id": "callback-38",
                "from": {"id": 2, "first_name": "Other", "is_bot": False},
                "data": callback_data,
                "message": {
                    "message_id": 88,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        }
        await self._ingest_and_wait(callback_update)
        self.assertFalse(self.store.agent_paused("a"))
        self.assertEqual(
            self.client.callback_answers[-1],
            ("callback-38", "仅所有者可以切换。"),
        )

    async def test_voice_transcription_is_marked_untrusted_in_prompt(self):
        class FakeTranscriber:
            async def transcribe(self, path):
                return "transcribed words"

        self.bridge.transcriber = FakeTranscriber()
        update = self.update(5, "")
        update["message"]["voice"] = {
            "file_id": "voice-file",
            "file_unique_id": "voice-unique",
            "file_size": 10,
        }
        await self._ingest_and_wait(update)
        self.assertIn("Voice transcription", self.runner.last_prompt)
        self.assertIn("untrusted user content", self.runner.last_prompt)
        self.assertIn("transcribed words", self.runner.last_prompt)

    async def test_private_owner_approval_button_is_authenticated_and_resumes_agent(self):
        self.runner.answer = (
            "需要确认\n"
            '<telegram_approval>{"title":"发布消息？","detail":"这会产生外部可见操作",'
            '"options":[{"id":"approve","label":"批准"},{"id":"reject","label":"拒绝"}]}'
            "</telegram_approval>"
        )
        await self._ingest_and_wait(self.update(6, "请发布"))

        markup = self.client.markups[-1]
        callback_data = markup["inline_keyboard"][0][0]["callback_data"]
        self.assertRegex(callback_data, r"^ap:[0-9a-f]{16}:approve$")
        self.runner.answer = "已按审批结果继续。"
        callback_update = {
            "update_id": 7,
            "callback_query": {
                "id": "callback-7",
                "from": {"id": 1, "first_name": "Owner", "is_bot": False},
                "data": callback_data,
                "message": {
                    "message_id": 77,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        }
        await self._ingest_and_wait(callback_update)

        self.assertEqual(self.client.callback_answers[-1], ("callback-7", "已选择：批准"))
        self.assertEqual(self.client.cleared_markups[-1], (1, 77))
        self.assertIn("Server-verified owner approval", self.runner.last_prompt)
        self.assertIn("selected_id=approve", self.runner.last_prompt)
        self.assertEqual(self.client.texts[-1][1], "已按审批结果继续。")

    async def test_non_owner_cannot_use_private_approval_button(self):
        self.runner.answer = (
            '<telegram_approval>{"title":"继续？","options":['
            '{"id":"yes","label":"继续"},{"id":"no","label":"取消"}]}'
            "</telegram_approval>"
        )
        await self._ingest_and_wait(self.update(8, "ask"))
        callback_data = self.client.markups[-1]["inline_keyboard"][0][0]["callback_data"]
        callback_update = {
            "update_id": 9,
            "callback_query": {
                "id": "callback-9",
                "from": {"id": 2, "first_name": "Other", "is_bot": False},
                "data": callback_data,
                "message": {
                    "message_id": 79,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        }
        await self._ingest_and_wait(callback_update)

        self.assertEqual(self.client.callback_answers[-1], ("callback-9", "仅所有者可以审批。"))
        self.assertEqual(self.runner.calls, 1)
