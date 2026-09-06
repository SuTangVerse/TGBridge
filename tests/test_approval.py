import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.approval import extract_approval_control
from sutang_telegram_bridge.store import DeliveryStore
from sutang_telegram_bridge.telegram import parse_update


class ApprovalProtocolTests(unittest.TestCase):
    def test_control_is_stripped_and_validated(self):
        visible, request = extract_approval_control(
            '稍等<telegram_approval>{"title":"继续？","detail":"会发送消息",'
            '"options":[{"id":"yes","label":"继续"},{"id":"no","label":"取消"}]}'
            "</telegram_approval>"
        )
        self.assertEqual(visible, "稍等")
        self.assertEqual(request.options[0].id, "yes")

    def test_duplicate_option_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            extract_approval_control(
                '<telegram_approval>{"title":"继续？","options":['
                '{"id":"same","label":"一"},{"id":"same","label":"二"}]}'
                "</telegram_approval>"
            )

    def test_callback_query_is_parsed_with_numeric_owner_identity(self):
        message = parse_update(
            "a",
            {
                "update_id": 9,
                "callback_query": {
                    "id": "cb",
                    "from": {"id": 123, "first_name": "Owner"},
                    "data": "ap:0123456789abcdef:yes",
                    "message": {"message_id": 8, "chat": {"id": 123, "type": "private"}},
                },
            },
        )
        self.assertEqual(message.event_type, "callback_query")
        self.assertEqual(message.sender_id, 123)
        self.assertEqual(message.callback_query_id, "cb")


class ApprovalStoreTests(unittest.TestCase):
    def test_choice_is_scoped_idempotent_and_owner_attributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DeliveryStore(Path(tmp) / "db.sqlite3")
            approval_id = store.create_approval(
                request_key="a:1:x",
                bot_key="a",
                chat_id=1,
                thread_id=None,
                source_message_id=10,
                title="Continue?",
                detail="Impact",
                options=[
                    {"id": "approve", "label": "Approve"},
                    {"id": "reject", "label": "Reject"},
                ],
            )
            unknown = store.resolve_approval(
                approval_id,
                "approve",
                bot_key="other",
                chat_id=1,
                owner_id=5,
                update_id=20,
            )
            resolved = store.resolve_approval(
                approval_id,
                "approve",
                bot_key="a",
                chat_id=1,
                owner_id=5,
                update_id=20,
            )
            replay = store.resolve_approval(
                approval_id,
                "approve",
                bot_key="a",
                chat_id=1,
                owner_id=5,
                update_id=20,
            )
            store.close()

        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decided_by"], 5)
        self.assertEqual(replay["status"], "replay")


if __name__ == "__main__":
    unittest.main()
