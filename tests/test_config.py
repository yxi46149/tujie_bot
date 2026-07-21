from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.config import Settings


class SettingsTests(unittest.TestCase):
    def test_multiple_required_chats_have_matching_buttons(self) -> None:
        environment = {
            "BOT_TOKEN": "123456:dummy-token",
            "REQUIRED_CHAT_IDS": "@one,-100123",
            "REQUIRED_JOIN_URLS": "https://t.me/one,https://t.me/+two",
            "REQUIRED_CHAT_NAMES": "频道一,频道二",
            "TIMEZONE": "Asia/Shanghai",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual(len(settings.required_chat_ids), 2)
        self.assertEqual(
            settings.join_buttons,
            (("频道一", "https://t.me/one"), ("频道二", "https://t.me/+two")),
        )

    def test_mismatched_chat_ids_and_urls_are_rejected(self) -> None:
        environment = {
            "BOT_TOKEN": "123456:dummy-token",
            "REQUIRED_CHAT_IDS": "@one,@two",
            "REQUIRED_JOIN_URLS": "https://t.me/one",
            "TIMEZONE": "Asia/Shanghai",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "数量必须"):
                Settings.from_env()

    def test_human_verify_configuration_is_parsed(self) -> None:
        environment = {
            "BOT_TOKEN": "123456:dummy-token",
            "TIMEZONE": "Asia/Shanghai",
            "HUMAN_VERIFY_ENABLED": "true",
            "HUMAN_VERIFY_CHAT_IDS": "-100123,@groupname",
            "HUMAN_VERIFY_TIMEOUT_SECONDS": "120",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertTrue(settings.human_verify_enabled)
        self.assertEqual(settings.human_verify_chat_ids, (-100123, "@groupname"))
        self.assertEqual(settings.human_verify_timeout_seconds, 120)

    def test_human_verify_timeout_defaults_to_two_minutes(self) -> None:
        environment = {
            "BOT_TOKEN": "123456:dummy-token",
            "TIMEZONE": "Asia/Shanghai",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.human_verify_timeout_seconds, 120)


if __name__ == "__main__":
    unittest.main()
