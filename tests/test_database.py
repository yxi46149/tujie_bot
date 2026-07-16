from __future__ import annotations

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

        first = await self.db.redeem_card(100, product_id)
        second = await self.db.redeem_card(100, product_id)
        third = await self.db.redeem_card(100, product_id)
        product = await self.db.get_product(product_id)

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertNotEqual(first.code, second.code)
        self.assertEqual(third.status, "insufficient_points")
        self.assertEqual(product["stock"], 0)

    async def test_out_of_stock_does_not_deduct_points(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 50)
        product_id = await self.db.add_product("空库存商品", 10)

        outcome = await self.db.redeem_card(100, product_id)
        user = await self.db.get_user(100)

        self.assertEqual(outcome.status, "out_of_stock")
        self.assertEqual(user["points"], 50)


if __name__ == "__main__":
    unittest.main()
