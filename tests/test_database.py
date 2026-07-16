from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.db")
        await self.db.initialize()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_referral_is_created_only_for_new_user_and_rewarded_once(
        self,
    ) -> None:
        await self.db.register_user(100, "inviter", "邀请人")
        created = await self.db.register_user(
            200, "invitee", "被邀请人", inviter_id=100
        )
        self.assertTrue(created)

        first = await self.db.verify_and_reward(200, 5)
        second = await self.db.verify_and_reward(200, 5)
        inviter = await self.db.get_user(100)

        self.assertTrue(first.rewarded)
        self.assertFalse(second.rewarded)
        self.assertEqual(inviter["points"], 5)
        self.assertEqual(await self.db.get_invite_counts(100), (1, 0))

        await self.db.register_user(300, "old_user", "旧用户")
        created_again = await self.db.register_user(
            300, "old_user", "旧用户", inviter_id=100
        )
        self.assertFalse(created_again)
        self.assertEqual(await self.db.get_invite_counts(100), (1, 0))

    async def test_daily_checkin_is_idempotent(self) -> None:
        await self.db.register_user(100, None, "用户")
        first = await self.db.claim_checkin(100, "2026-07-16", 1)
        second = await self.db.claim_checkin(100, "2026-07-16", 1)
        next_day = await self.db.claim_checkin(100, "2026-07-17", 1)

        self.assertTrue(first.claimed)
        self.assertFalse(second.claimed)
        self.assertTrue(next_day.claimed)
        self.assertEqual(next_day.points, 2)

    async def test_card_redemption_is_atomic_and_decrements_stock(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 20)
        product_id = await self.db.add_product("测试卡", 10)
        inserted = await self.db.add_cards(product_id, ["CODE-1", "CODE-2", "CODE-1"])
        self.assertEqual(inserted, 2)

        first_intent = await self.db.create_redemption_intent(100, product_id, 600)
        same_pending_intent = await self.db.create_redemption_intent(
            100, product_id, 600
        )
        self.assertEqual(same_pending_intent, first_intent)
        await self.db.register_user(101, None, "其他用户")
        stolen = await self.db.redeem_card(101, first_intent)
        self.assertEqual(stolen.status, "invalid_intent")
        first = await self.db.redeem_card(100, first_intent)
        replay = await self.db.redeem_card(100, first_intent)
        second_intent = await self.db.create_redemption_intent(100, product_id, 600)
        second = await self.db.redeem_card(100, second_intent)
        third_intent = await self.db.create_redemption_intent(100, product_id, 600)
        third = await self.db.redeem_card(100, third_intent)
        product = await self.db.get_product(product_id)
        redemptions = await self.db.get_user_redemptions(100)

        self.assertEqual(first.status, "ok")
        self.assertEqual(replay.status, "already_redeemed")
        self.assertEqual(replay.code, first.code)
        self.assertEqual(second.status, "ok")
        self.assertNotEqual(first.code, second.code)
        self.assertEqual(third.status, "insufficient_points")
        self.assertEqual(product["stock"], 0)
        self.assertEqual(len(redemptions), 2)

    async def test_out_of_stock_does_not_deduct_points(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 50)
        product_id = await self.db.add_product("空库存商品", 10)
        intent = await self.db.create_redemption_intent(100, product_id, 600)

        outcome = await self.db.redeem_card(100, intent)
        user = await self.db.get_user(100)

        self.assertEqual(outcome.status, "out_of_stock")
        self.assertEqual(user["points"], 50)

    async def test_expired_redemption_intent_does_not_deduct_points(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 10)
        product_id = await self.db.add_product("测试商品", 10)
        await self.db.add_cards(product_id, ["CODE-1"])
        intent = await self.db.create_redemption_intent(100, product_id, -1)

        outcome = await self.db.redeem_card(100, intent)
        user = await self.db.get_user(100)
        product = await self.db.get_product(product_id)

        self.assertEqual(outcome.status, "expired_intent")
        self.assertEqual(user["points"], 10)
        self.assertEqual(product["stock"], 1)

    async def test_daily_invite_reward_limit_records_without_extra_points(self) -> None:
        await self.db.register_user(100, "inviter", "邀请人")
        await self.db.register_user(200, None, "用户一", inviter_id=100)
        await self.db.register_user(201, None, "用户二", inviter_id=100)
        start = "2026-07-16T16:00:00+00:00"
        end = "2026-07-17T16:00:00+00:00"

        first = await self.db.verify_and_reward(200, 5, 1, start, end)
        second = await self.db.verify_and_reward(201, 5, 1, start, end)
        inviter = await self.db.get_user(100)

        self.assertTrue(first.rewarded)
        self.assertTrue(second.settled)
        self.assertTrue(second.limited)
        self.assertFalse(second.rewarded)
        self.assertEqual(inviter["points"], 5)
        self.assertEqual(await self.db.get_invite_counts(100), (2, 0))

    async def test_concurrent_replay_only_redeems_one_card(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 20)
        product_id = await self.db.add_product("并发商品", 10)
        await self.db.add_cards(product_id, ["ONLY-CODE", "SECOND-CODE"])
        intent = await self.db.create_redemption_intent(100, product_id, 600)

        first, second = await asyncio.gather(
            self.db.redeem_card(100, intent),
            self.db.redeem_card(100, intent),
        )
        user = await self.db.get_user(100)
        redemptions = await self.db.get_user_redemptions(100)

        self.assertEqual({first.status, second.status}, {"ok", "already_redeemed"})
        self.assertEqual(first.code, second.code)
        self.assertEqual(user["points"], 10)
        self.assertEqual(len(redemptions), 1)
        self.assertEqual(await self.db.quick_check(), "ok")

    async def test_initialize_upgrades_legacy_database_without_losing_users(
        self,
    ) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL DEFAULT '',
                    points INTEGER NOT NULL DEFAULT 0 CHECK(points >= 0),
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO users(
                    user_id, username, first_name, points,
                    is_verified, created_at, updated_at
                ) VALUES (999, 'legacy', '旧用户', 42, 1, 'old', 'old')
                """
            )
            connection.commit()
        finally:
            connection.close()

        upgraded = Database(legacy_path)
        await upgraded.initialize()
        user = await upgraded.get_user(999)
        async with upgraded.connection() as connection:
            intent_table = await (
                await connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name = 'redemption_intents'
                    """
                )
            ).fetchone()

        self.assertEqual(user["username"], "legacy")
        self.assertEqual(user["points"], 42)
        self.assertIsNotNone(intent_table)
        self.assertEqual(await upgraded.quick_check(), "ok")


if __name__ == "__main__":
    unittest.main()
