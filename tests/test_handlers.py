from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.config import Settings
from app.database import Database
from app.handlers import answer_callback, build_router
from app.keyboards import main_menu


class HandlerSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_response_is_forced_to_clicking_users_private_chat(
        self,
    ) -> None:
        callback = SimpleNamespace(from_user=SimpleNamespace(id=123456))
        bot = SimpleNamespace(send_message=AsyncMock())

        await answer_callback(callback, bot, "secret", protect_content=True)

        bot.send_message.assert_awaited_once_with(
            123456,
            "secret",
            reply_markup=None,
            protect_content=True,
        )

    def test_main_menu_contains_every_required_chat_link(self) -> None:
        keyboard = main_menu(
            (("通知频道", "https://t.me/one"), ("交流群", "https://t.me/two"))
        )

        self.assertEqual(keyboard.inline_keyboard[0][0].url, "https://t.me/one")
        self.assertEqual(keyboard.inline_keyboard[1][0].url, "https://t.me/two")

    def test_main_menu_contains_points_and_invite_rank_buttons(self) -> None:
        keyboard = main_menu(())
        callback_data = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }

        self.assertIn("menu:pointrank", callback_data)
        self.assertIn("menu:rank", callback_data)

    def test_router_builds_with_private_child_and_group_guards(self) -> None:
        settings = Settings(
            bot_token="123456:dummy-token",
            admin_ids=frozenset(),
            required_chat_ids=(),
            required_join_urls=(),
            required_chat_names=(),
            invite_reward=5,
            invite_daily_reward_limit=20,
            checkin_reward=1,
            lottery_cost=5,
            verify_cooldown_seconds=15,
            verify_max_concurrency=5,
            redemption_intent_ttl_seconds=600,
            timezone_name="Asia/Shanghai",
            database_path=Path("unused.db"),
        )

        router = build_router(settings, Database(settings.database_path))

        self.assertEqual(len(router.sub_routers), 1)
        self.assertGreaterEqual(len(router.message.handlers), 1)
        self.assertGreaterEqual(len(router.callback_query.handlers), 1)


if __name__ == "__main__":
    unittest.main()
