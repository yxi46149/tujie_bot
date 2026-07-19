from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        end = (now + timedelta(hours=1)).isoformat(timespec="seconds")

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

    async def test_lottery_points_prize_charges_cost_and_adds_reward(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 10)
        prize_id = await self.db.add_lottery_prize("小额积分", "points", 1, 2)

        outcome = await self.db.draw_lottery(100, 5)
        user = await self.db.get_user(100)

        self.assertIsNotNone(prize_id)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.prize_type, "points")
        self.assertEqual(outcome.points_delta, 2)
        self.assertEqual(outcome.points, 7)
        self.assertEqual(user["points"], 7)

    async def test_lottery_product_prize_consumes_card_and_records_redemption(
        self,
    ) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 10)
        product_id = await self.db.add_product("抽奖卡密", 99)
        await self.db.add_cards(product_id, ["LOTTERY-CODE"])
        prize_id = await self.db.add_lottery_prize(
            "抽奖卡密", "product", 1, product_id=product_id
        )

        outcome = await self.db.draw_lottery(100, 5)
        user = await self.db.get_user(100)
        product = await self.db.get_product(product_id)
        redemptions = await self.db.get_user_redemptions(100)

        self.assertIsNotNone(prize_id)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.prize_type, "product")
        self.assertEqual(outcome.code, "LOTTERY-CODE")
        self.assertEqual(outcome.points, 5)
        self.assertEqual(user["points"], 5)
        self.assertEqual(product["stock"], 0)
        self.assertEqual(len(redemptions), 1)
        self.assertEqual(redemptions[0]["code"], "LOTTERY-CODE")

    async def test_lottery_without_available_prizes_does_not_deduct_points(
        self,
    ) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 10)
        product_id = await self.db.add_product("空库存商品", 99)
        await self.db.add_lottery_prize("空库存卡密", "product", 1, product_id=product_id)

        outcome = await self.db.draw_lottery(100, 5)
        user = await self.db.get_user(100)

        self.assertEqual(outcome.status, "no_prizes")
        self.assertEqual(user["points"], 10)

    async def test_lottery_insufficient_points_does_not_draw(self) -> None:
        await self.db.register_user(100, None, "用户")
        await self.db.adjust_points(100, 4)
        await self.db.add_lottery_prize("谢谢参与", "none", 1)

        outcome = await self.db.draw_lottery(100, 5)
        user = await self.db.get_user(100)

        self.assertEqual(outcome.status, "insufficient_points")
        self.assertEqual(outcome.points, 4)
        self.assertEqual(user["points"], 4)

    async def test_group_lottery_points_prize_awards_all_winners(self) -> None:
        await self.db.register_user(100, None, "管理员")
        await self.db.register_user(200, "one", "用户一")
        await self.db.register_user(201, "two", "用户二")
        created = await self.db.create_group_lottery(
            -1001, 100, "群福利", "points", 3, 2
        )

        self.assertEqual(created.status, "ok")
        self.assertIsNotNone(created.lottery_id)
        first_join = await self.db.join_group_lottery(
            created.lottery_id, 200, "one", "用户一"
        )
        duplicate_join = await self.db.join_group_lottery(
            created.lottery_id, 200, "one", "用户一"
        )
        second_join = await self.db.join_group_lottery(
            created.lottery_id, 201, "two", "用户二"
        )
        outcome = await self.db.draw_group_lottery(created.lottery_id)
        user_one = await self.db.get_user(200)
        user_two = await self.db.get_user(201)
        join_after_draw = await self.db.join_group_lottery(
            created.lottery_id, 100, None, "管理员"
        )

        self.assertEqual(first_join.participant_count, 1)
        self.assertEqual(duplicate_join.participant_count, 1)
        self.assertEqual(second_join.participant_count, 2)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.participant_count, 2)
        self.assertEqual(len(outcome.winners), 2)
        self.assertEqual(user_one["points"], 3)
        self.assertEqual(user_two["points"], 3)
        self.assertEqual(join_after_draw.status, "drawn")

    async def test_group_lottery_product_prize_consumes_card(self) -> None:
        await self.db.register_user(100, None, "管理员")
        await self.db.register_user(200, "winner", "中奖用户")
        product_id = await self.db.add_product("群抽奖卡密", 50)
        await self.db.add_cards(product_id, ["GROUP-CODE"])
        created = await self.db.create_group_lottery(
            -1001, 100, "群卡密", "product", product_id, 1
        )
        await self.db.join_group_lottery(created.lottery_id, 200, "winner", "中奖用户")

        outcome = await self.db.draw_group_lottery(created.lottery_id)
        product = await self.db.get_product(product_id)
        redemptions = await self.db.get_user_redemptions(200)

        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.prize_type, "product")
        self.assertEqual(len(outcome.winners), 1)
        self.assertEqual(outcome.winners[0].code, "GROUP-CODE")
        self.assertEqual(product["stock"], 0)
        self.assertEqual(len(redemptions), 1)
        self.assertEqual(redemptions[0]["code"], "GROUP-CODE")

    async def test_group_lottery_rejects_product_with_insufficient_stock(self) -> None:
        await self.db.register_user(100, None, "管理员")
        product_id = await self.db.add_product("库存不足商品", 50)

        created = await self.db.create_group_lottery(
            -1001, 100, "库存不足", "product", product_id, 1
        )

        self.assertEqual(created.status, "insufficient_stock")
        self.assertEqual(created.stock, 0)

    async def test_count_group_lottery_triggers_at_target_count(self) -> None:
        await self.db.register_user(100, None, "管理员")
        await self.db.register_user(200, "one", "用户一")
        await self.db.register_user(201, "two", "用户二")
        await self.db.register_user(202, "three", "用户三")
        created = await self.db.create_group_lottery(
            -1001,
            100,
            "满人抽奖",
            "points",
            5,
            1,
            trigger_text="抽奖",
            draw_mode="count",
            target_participants=2,
        )

        first_join = await self.db.join_group_lottery(
            created.lottery_id, 200, "one", "用户一"
        )
        await self.db.set_group_lottery_feedback(created.lottery_id, 9001)
        second_join = await self.db.join_group_lottery(
            created.lottery_id, 201, "two", "用户二"
        )
        duplicate_join = await self.db.join_group_lottery(
            created.lottery_id, 200, "one-new", "用户一新"
        )
        over_limit_join = await self.db.join_group_lottery(
            created.lottery_id, 202, "three", "用户三"
        )

        self.assertEqual(created.status, "ok")
        self.assertEqual(created.target_participants, 2)
        self.assertEqual(first_join.status, "ok")
        self.assertFalse(first_join.should_draw)
        self.assertEqual(second_join.status, "ok")
        self.assertTrue(second_join.should_draw)
        self.assertEqual(second_join.participant_count, 2)
        self.assertEqual(second_join.previous_feedback_message_id, 9001)
        self.assertEqual(duplicate_join.status, "already_joined")
        self.assertEqual(duplicate_join.participant_count, 2)
        self.assertEqual(over_limit_join.status, "filled")
        self.assertEqual(over_limit_join.participant_count, 2)

    async def test_due_group_lotteries_only_returns_elapsed_timed_lotteries(
        self,
    ) -> None:
        await self.db.register_user(100, None, "管理员")
        now = datetime.now(timezone.utc)
        past = (now - timedelta(seconds=1)).isoformat(timespec="seconds")
        future = (now + timedelta(minutes=5)).isoformat(timespec="seconds")
        due_created = await self.db.create_group_lottery(
            -1001,
            100,
            "到期抽奖",
            "points",
            5,
            1,
            trigger_text="到期",
            draw_mode="time",
            draw_at=past,
        )
        await self.db.create_group_lottery(
            -1001,
            100,
            "未到期抽奖",
            "points",
            5,
            1,
            trigger_text="未到期",
            draw_mode="time",
            draw_at=future,
        )

        due = await self.db.list_due_group_lotteries(
            now.isoformat(timespec="seconds")
        )

        self.assertEqual([row["id"] for row in due], [due_created.lottery_id])

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
