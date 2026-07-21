from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Dispatcher

from app.config import Settings
from app.database import Database
from app.handlers import (
    answer_callback,
    build_router,
    create_human_verify_challenge,
    parse_bot_command,
)
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

    def test_human_verify_challenge_has_three_choices(self) -> None:
        challenge = create_human_verify_challenge()

        self.assertEqual(len(challenge.options), 3)
        self.assertEqual(len(set(challenge.options)), 3)
        self.assertIn(challenge.answer, challenge.options)

    def test_parse_bot_command_ignores_bare_or_invalid_slash(self) -> None:
        self.assertIsNone(parse_bot_command("/"))
        self.assertIsNone(parse_bot_command("/中文"))
        self.assertIsNone(parse_bot_command("/points@"))

    def test_parse_bot_command_extracts_name_and_mention(self) -> None:
        command = parse_bot_command("/Points@TujieBot extra")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.name, "points")
        self.assertEqual(command.mention, "tujiebot")

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
            human_verify_enabled=False,
            human_verify_chat_ids=(),
            human_verify_timeout_seconds=300,
            timezone_name="Asia/Shanghai",
            database_path=Path("unused.db"),
        )

        router = build_router(settings, Database(settings.database_path))

        self.assertEqual(len(router.sub_routers), 1)
        self.assertGreaterEqual(len(router.message.handlers), 1)
        self.assertGreaterEqual(len(router.callback_query.handlers), 1)
        self.assertGreaterEqual(len(router.chat_member.handlers), 1)
        root_message_handlers = {
            handler.callback.__name__ for handler in router.message.handlers
        }
        self.assertIn("command_group_checkin", root_message_handlers)
        self.assertIn("reject_group_add_cards", root_message_handlers)

        dispatcher = Dispatcher()
        dispatcher.include_router(router)
        self.assertIn("chat_member", dispatcher.resolve_used_update_types())

    def test_points_rank_command_is_available_from_root_router(self) -> None:
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
            human_verify_enabled=False,
            human_verify_chat_ids=(),
            human_verify_timeout_seconds=300,
            timezone_name="Asia/Shanghai",
            database_path=Path("unused.db"),
        )

        router = build_router(settings, Database(settings.database_path))
        root_message_handlers = {
            handler.callback.__name__ for handler in router.message.handlers
        }
        private_message_handlers = {
            handler.callback.__name__
            for handler in router.sub_routers[0].message.handlers
        }

        self.assertIn("command_points_rank", root_message_handlers)
        self.assertNotIn("command_points_rank", private_message_handlers)

    def test_checkin_command_is_available_from_root_router(self) -> None:
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
            human_verify_enabled=False,
            human_verify_chat_ids=(),
            human_verify_timeout_seconds=300,
            timezone_name="Asia/Shanghai",
            database_path=Path("unused.db"),
        )

        router = build_router(settings, Database(settings.database_path))
        root_message_handlers = {
            handler.callback.__name__ for handler in router.message.handlers
        }
        private_message_handlers = {
            handler.callback.__name__
            for handler in router.sub_routers[0].message.handlers
        }

        self.assertIn("command_group_checkin", root_message_handlers)
        self.assertIn("command_checkin", private_message_handlers)


if __name__ == "__main__":
    unittest.main()
