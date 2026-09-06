import sys
import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.models import AgentConfig
from sutang_telegram_bridge.models import TranscriptionConfig
from sutang_telegram_bridge.runner import AgentRunner
from sutang_telegram_bridge.telegram import TelegramClient, parse_update
from sutang_telegram_bridge.transcription import VoiceTranscriber


class TelegramParsingTests(unittest.TestCase):
    def test_my_chat_member_preserves_group_and_actor(self):
        update = {
            "update_id": 8,
            "my_chat_member": {
                "chat": {
                    "id": -20,
                    "type": "supergroup",
                    "title": "Example Room",
                },
                "from": {
                    "id": 2,
                    "first_name": "Admin",
                    "is_bot": False,
                },
                "new_chat_member": {"status": "member"},
            },
        }
        message = parse_update("a", update)
        self.assertEqual(message.event_type, "my_chat_member")
        self.assertEqual(message.chat_id, -20)
        self.assertEqual(message.chat_title, "Example Room")

    def test_reply_and_topic_identity_are_preserved(self):
        update = {
            "update_id": 9,
            "message": {
                "message_id": 3,
                "message_thread_id": 7,
                "chat": {"id": -10, "type": "supergroup"},
                "from": {"id": 2, "first_name": "One", "username": "one", "is_bot": False},
                "text": "hello",
                "reply_to_message": {
                    "message_id": 2,
                    "from": {"id": 4, "first_name": "Two", "is_bot": False},
                    "text": "earlier",
                },
            },
        }
        message = parse_update("a", update)
        self.assertEqual(message.thread_id, 7)
        self.assertEqual(message.reply_to["from"]["id"], 4)


class TelegramBotToBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_bot_text_uses_native_username_target(self):
        client = TelegramClient("test-token")
        calls = []

        async def fake_request(method, payload=None, file=None):
            calls.append((method, payload, file))
            return {}

        client.request = fake_request
        await client.send_bot_text("TargetExampleBot", "hello")
        self.assertEqual(
            calls,
            [("sendMessage", {"chat_id": "@TargetExampleBot", "text": "hello"}, None)],
        )

    async def test_send_bot_text_rejects_invalid_target(self):
        client = TelegramClient("test-token")
        with self.assertRaises(ValueError):
            await client.send_bot_text("not a username", "hello")

    async def test_send_bot_text_redacts_access_material(self):
        client = TelegramClient("test-token")
        calls = []
        fake_access = "api_" + "key=" + ("x" * 20)

        async def fake_request(method, payload=None, file=None):
            calls.append((method, payload, file))
            return {}

        client.request = fake_request
        await client.send_bot_text("@TargetExampleBot", "inspect " + fake_access)
        self.assertNotIn(fake_access, calls[0][1]["text"])
        self.assertIn("[REDACTED ACCESS MATERIAL]", calls[0][1]["text"])


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_uses_stdin_and_captures_stdout(self):
        agent = AgentConfig(
            "a",
            "TOKEN",
            (
                sys.executable,
                "-c",
                "import sys; print('answer:' + sys.stdin.read())",
            ),
        )
        answer = await AgentRunner().run(agent, "hello", True, 5)
        self.assertEqual(answer, "answer:hello")

    async def test_runner_timeout_terminates_process_group(self):
        agent = AgentConfig(
            "a",
            "TOKEN",
            (sys.executable, "-c", "import time; time.sleep(60)"),
        )
        with self.assertRaises(TimeoutError):
            await AgentRunner().run(agent, "hello", True, 0.05)

    async def test_voice_transcriber_uses_fixed_argv_and_audio_path(self):
        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "voice.ogg"
            audio.write_bytes(b"fake")
            config = TranscriptionConfig(
                (sys.executable, "-c", "import pathlib,sys; print('heard:' + pathlib.Path(sys.argv[1]).name)")
            )
            transcript = await VoiceTranscriber(config).transcribe(audio)
            self.assertEqual(transcript, "heard:voice.ogg")
