from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)

from app.main import (
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

        self.assertIn("start", commands)
        self.assertIn("language", commands)
        self.assertIn("shop", commands)
        self.assertIn("lottery", commands)
        self.assertIn("grouplottery", commands)

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


if __name__ == "__main__":
    unittest.main()
