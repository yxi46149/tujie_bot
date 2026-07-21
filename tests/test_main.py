from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from app.main import (
    admin_private_commands,
    group_admin_commands,
    group_commands,
    private_commands,
    set_commands,
)


class CommandMenuTests(unittest.IsolatedAsyncioTestCase):
    def test_group_command_menu_only_shows_public_group_commands(self) -> None:
        commands = [command.command for command in group_commands()]
        english_descriptions = [command.description for command in group_commands("en")]

        self.assertEqual(commands, ["checkin", "pointrank"])
        self.assertEqual(english_descriptions, ["Daily check-in", "Points ranking"])
        self.assertNotIn("shop", commands)
        self.assertNotIn("grouplottery", commands)

    def test_group_admin_command_menu_adds_lottery_commands(self) -> None:
        commands = [command.command for command in group_admin_commands()]

        self.assertEqual(
            commands,
            ["checkin", "pointrank", "grouplottery", "lotteries", "drawlottery"],
        )

    def test_private_command_menu_keeps_full_user_commands(self) -> None:
        commands = [command.command for command in private_commands()]

        self.assertEqual(
            commands,
            [
                "start",
                "points",
                "verify",
                "invite",
                "myinvites",
                "checkin",
                "shop",
                "lottery",
                "mycards",
                "pointrank",
                "rank",
                "language",
                "lang",
                "help",
            ],
        )
        self.assertNotIn("grouplottery", commands)
        self.assertNotIn("lotteries", commands)
        self.assertNotIn("drawlottery", commands)
        self.assertNotIn("addproduct", commands)
        self.assertNotIn("addcards", commands)

    def test_admin_private_command_menu_adds_inventory_commands(self) -> None:
        commands = [command.command for command in admin_private_commands()]

        self.assertIn("lang", commands)
        self.assertIn("admin", commands)
        self.assertIn("stats", commands)
        self.assertIn("products", commands)
        self.assertIn("addproduct", commands)
        self.assertIn("addcards", commands)
        self.assertIn("toggleproduct", commands)
        self.assertIn("lotteryprizes", commands)
        self.assertIn("addlotteryprize", commands)
        self.assertIn("togglelotteryprize", commands)
        self.assertIn("addpoints", commands)
        self.assertNotIn("grouplottery", commands)
        self.assertNotIn("lotteries", commands)
        self.assertNotIn("drawlottery", commands)

    async def test_set_commands_registers_private_and_group_scopes(self) -> None:
        bot = SimpleNamespace(set_my_commands=AsyncMock())

        await set_commands(bot)

        self.assertEqual(bot.set_my_commands.await_count, 8)
        calls = bot.set_my_commands.await_args_list
        self.assertIsInstance(calls[0].kwargs["scope"], BotCommandScopeDefault)
        self.assertIsInstance(calls[1].kwargs["scope"], BotCommandScopeAllPrivateChats)
        self.assertIsInstance(calls[2].kwargs["scope"], BotCommandScopeAllGroupChats)
        self.assertIsInstance(
            calls[3].kwargs["scope"], BotCommandScopeAllChatAdministrators
        )
        self.assertIsNone(calls[0].kwargs["language_code"])
        self.assertEqual(calls[4].kwargs["language_code"], "en")
        self.assertIsInstance(calls[4].kwargs["scope"], BotCommandScopeDefault)
        self.assertIsInstance(calls[6].kwargs["scope"], BotCommandScopeAllGroupChats)
        self.assertIsInstance(
            calls[7].kwargs["scope"], BotCommandScopeAllChatAdministrators
        )
        self.assertEqual(
            [command.command for command in calls[2].args[0]],
            ["checkin", "pointrank"],
        )
        self.assertEqual(
            [command.command for command in calls[3].args[0]],
            ["checkin", "pointrank", "grouplottery", "lotteries", "drawlottery"],
        )
        self.assertEqual(
            [command.description for command in calls[6].args[0]],
            ["Daily check-in", "Points ranking"],
        )

    async def test_set_commands_registers_admin_private_scopes(self) -> None:
        bot = SimpleNamespace(set_my_commands=AsyncMock())

        await set_commands(bot, frozenset({1001}))

        self.assertEqual(bot.set_my_commands.await_count, 10)
        calls = bot.set_my_commands.await_args_list
        self.assertIsInstance(calls[4].kwargs["scope"], BotCommandScopeChat)
        self.assertEqual(calls[4].kwargs["scope"].chat_id, 1001)
        self.assertIsNone(calls[4].kwargs["language_code"])
        self.assertIsInstance(calls[9].kwargs["scope"], BotCommandScopeChat)
        self.assertEqual(calls[9].kwargs["language_code"], "en")
        self.assertIn("addcards", [command.command for command in calls[4].args[0]])


if __name__ == "__main__":
    unittest.main()
