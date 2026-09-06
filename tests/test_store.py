import json
import tempfile
import unittest
from pathlib import Path

from sutang_telegram_bridge.store import DeliveryStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DeliveryStore(Path(self.temp.name) / "delivery.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_update_is_idempotent_and_recovers_processing(self):
        payload = {"update_id": 7, "message": {}}
        self.assertTrue(self.store.put_update("a", 7, payload, 1, 2))
        self.assertFalse(self.store.put_update("a", 7, payload, 1, 2))
        self.store.set_processing("a", 7)
        self.store.recover()
        self.assertEqual(self.store.get_update("a", 7)["state"], "received")

    def test_generated_reply_is_durable_until_done(self):
        self.store.put_update("a", 8, {"update_id": 8}, 1, 2)
        operations = [{"kind": "text", "text": "hello"}]
        self.store.set_generated("a", 8, operations)
        row = self.store.get_update("a", 8)
        self.assertEqual(json.loads(row["response"]), operations)
        self.store.done("a", 8)
        row = self.store.get_update("a", 8)
        self.assertEqual(row["state"], "done")
        self.assertIsNone(row["payload"])

    def test_delivery_failure_preserves_cached_reply_and_reaches_dead_letter(self):
        self.store.put_update("a", 9, {"update_id": 9}, 1, 2)
        self.store.set_processing("a", 9)
        operations = [{"kind": "text", "text": "retry safely"}]
        self.store.set_generated("a", 9, operations)

        for expected_attempts in range(2, 6):
            self.store.delivery_failed("a", 9, "TelegramError")
            row = self.store.get_update("a", 9)
            self.assertEqual(row["attempts"], expected_attempts)
            self.assertEqual(
                row["state"],
                "dead" if expected_attempts == 5 else "generated",
            )
            self.assertEqual(json.loads(row["response"]), operations)
            self.assertEqual(row["error"], "TelegramError")

    def test_media_assets_are_scoped_to_bot_and_chat(self):
        asset = self.store.register_asset("a", -10, "sticker", "telegram-file-id")
        self.assertEqual(self.store.resolve_asset("a", -10, asset, "sticker"), "telegram-file-id")
        self.assertIsNone(self.store.resolve_asset("b", -10, asset, "sticker"))
        self.assertIsNone(self.store.resolve_asset("a", -11, asset, "sticker"))

    def test_dynamic_modes_and_agent_pauses_are_durable(self):
        self.store.set_group_mode(-10, "mentions")
        self.store.set_agent_paused("a", True)
        self.store.set_agent_group_paused("a", -10, True)
        self.assertEqual(self.store.group_mode(-10), "mentions")
        self.assertTrue(self.store.agent_paused("a"))
        self.assertTrue(self.store.agent_group_paused("a", -10))
        self.store.set_agent_paused("a", False)
        self.store.set_agent_group_paused("a", -10, False)
        self.assertFalse(self.store.agent_paused("a"))
        self.assertFalse(self.store.agent_group_paused("a", -10))

    def test_bot_pair_budget_is_unordered_and_restart_durable(self):
        for index in range(4):
            source, target = ((101, 102) if index % 2 == 0 else (102, 101))
            self.assertTrue(
                self.store.reserve_bot_pair_call(
                    call_id=f"call-{index}",
                    surface="private",
                    chat_id=source,
                    thread_id=None,
                    source_bot_id=source,
                    target_bot_id=target,
                    limit=4,
                    window_seconds=120,
                    now=1000 + index,
                )
            )
        path = self.store.path
        self.store.close()
        self.store = DeliveryStore(path)
        self.assertFalse(
            self.store.reserve_bot_pair_call(
                call_id="call-blocked",
                surface="group",
                chat_id=-10,
                thread_id=7,
                source_bot_id=102,
                target_bot_id=101,
                limit=4,
                window_seconds=120,
                now=1004,
            )
        )

    def test_group_epoch_is_idempotent_and_caps_total_bot_calls(self):
        self.assertEqual(self.store.begin_group_epoch(-10, 7, 20, now=1000), 1)
        self.assertEqual(self.store.begin_group_epoch(-10, 7, 20, now=1001), 1)
        for index, pair in enumerate(((101, 102), (103, 104))):
            reservation = self.store.reserve_group_bot_call(
                call_id=f"group-{index}",
                chat_id=-10,
                thread_id=7,
                source_bot_id=pair[0],
                target_bot_id=pair[1],
                pair_limit=20,
                pair_window_seconds=120,
                group_limit=2,
                now=1002 + index,
            )
            self.assertTrue(reservation.allowed)
            self.assertEqual(reservation.epoch, 1)
        blocked = self.store.reserve_group_bot_call(
            call_id="group-blocked",
            chat_id=-10,
            thread_id=7,
            source_bot_id=105,
            target_bot_id=106,
            pair_limit=20,
            pair_window_seconds=120,
            group_limit=2,
            now=1004,
        )
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "group_limit")

        path = self.store.path
        self.store.close()
        self.store = DeliveryStore(path)
        blocked_after_restart = self.store.reserve_group_bot_call(
            call_id="group-blocked-after-restart",
            chat_id=-10,
            thread_id=7,
            source_bot_id=105,
            target_bot_id=106,
            pair_limit=20,
            pair_window_seconds=120,
            group_limit=2,
            now=1004.5,
        )
        self.assertFalse(blocked_after_restart.allowed)
        self.assertEqual(blocked_after_restart.reason, "group_limit")

        self.assertEqual(self.store.begin_group_epoch(-10, 7, 21, now=1005), 2)
        admitted = self.store.reserve_group_bot_call(
            call_id="group-new-epoch",
            chat_id=-10,
            thread_id=7,
            source_bot_id=105,
            target_bot_id=106,
            pair_limit=20,
            pair_window_seconds=120,
            group_limit=2,
            now=1006,
        )
        self.assertTrue(admitted.allowed)
        self.assertEqual(admitted.epoch, 2)
        snapshot = self.store.group_flow_status(
            -10, 7, pair_window_seconds=120, now=1007
        )
        self.assertEqual(snapshot["epoch"], 2)
        self.assertEqual(snapshot["bot_calls"], 1)

    def test_group_decision_is_random_scoped_and_single_use(self):
        group, created = self.store.register_group(
            -20, "Example Room", notification_bot="a"
        )
        self.assertTrue(created)
        self.assertRegex(group["decision_id"], r"^[0-9a-f]{16}$")
        resolved = self.store.resolve_group_decision(
            group["decision_id"], "a", "trusted"
        )
        self.assertEqual(resolved["trust_state"], "trusted")
        self.assertIsNone(
            self.store.resolve_group_decision(
                group["decision_id"], "a", "external"
            )
        )

    def test_anomaly_notice_is_deduplicated_without_raw_message(self):
        first = self.store.ensure_anomaly_notice(
            request_key="a:44:1",
            bot_key="a",
            chat_id=-10,
            owner_id=1,
            error_type="RuntimeError",
        )
        second = self.store.ensure_anomaly_notice(
            request_key="a:44:1",
            bot_key="a",
            chat_id=-10,
            owner_id=1,
            error_type="RuntimeError",
        )
        self.assertEqual(first["notice_id"], second["notice_id"])
        self.assertNotIn("message", first.keys())

    def test_dead_update_can_be_requeued_only_while_payload_exists(self):
        payload = {"update_id": 90, "message": {"text": "retry me"}}
        self.store.put_update("a", 90, payload, -10, 9)
        for _ in range(5):
            self.store.set_processing("a", 90)
            self.store.retry("a", 90, "RuntimeError")
        self.assertEqual(self.store.get_update("a", 90)["state"], "dead")
        self.assertTrue(self.store.requeue_dead("a", 90))
        self.assertEqual(self.store.get_update("a", 90)["state"], "received")

    def test_dead_letters_are_scoped_to_bot(self):
        self.store.put_update("a", 91, {"update_id": 91}, 1, 1)
        self.store.put_update("b", 92, {"update_id": 92}, 1, 1)
        for bot_key, update_id in (("a", 91), ("b", 92)):
            for _ in range(5):
                self.store.set_processing(bot_key, update_id)
                self.store.retry(bot_key, update_id, "RuntimeError")
        rows = self.store.dead_letters("a")
        self.assertEqual([row["update_id"] for row in rows], [91])
        self.assertEqual(rows[0]["error"], "RuntimeError")
