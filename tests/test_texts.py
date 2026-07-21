from __future__ import annotations

import unittest

from app.group_lottery import participation_message
from app.keyboards import invite_menu, language_menu, main_menu
from app.texts import (
    invite_copy_text,
    invite_message,
    points_message,
    points_rank_message,
    profile,
    stock_added_message,
)


class TextFormattingTests(unittest.TestCase):
    def test_points_rank_masks_usernames_and_names(self) -> None:
        message = points_rank_message(
            [
                {"username": "alice_secret", "first_name": "Alice", "points": 10},
                {"username": None, "first_name": "张小明", "points": 5},
            ]
        )

        self.assertIn("@al***et", message)
        self.assertIn("张*明", message)
        self.assertNotIn("alice_secret", message)
        self.assertNotIn("张小明", message)

    def test_user_texts_support_english(self) -> None:
        dashboard = profile(100, 12, 5, "en")
        points = points_message(12, 3, "en")

        self.assertIn("Dashboard", dashboard)
        self.assertIn("Language", dashboard)
        self.assertIn("Available points", points)
        self.assertNotIn("个人中心", dashboard)

    def test_invite_message_contains_copyable_promo_text(self) -> None:
        link = "https://t.me/txxxx?start=ref_100"
        message = invite_message(link, 5)
        copy_text = invite_copy_text(link)

        self.assertIn("签到即可领取codex接码CDK", message)
        self.assertEqual(copy_text, f"{link}\n签到即可领取codex接码CDK")

    def test_invite_menu_has_copy_text_button(self) -> None:
        copy_text = "https://t.me/txxxx\n签到即可领取codex接码CDK"
        keyboard = invite_menu(copy_text)
        button = keyboard.inline_keyboard[0][0]

        self.assertEqual(button.text, "📋 一键复制邀请文案")
        self.assertIsNotNone(button.copy_text)
        assert button.copy_text is not None
        self.assertEqual(button.copy_text.text, copy_text)

    def test_stock_added_message_escapes_product_name(self) -> None:
        message = stock_added_message("codex<接码>", 8)

        self.assertIn("管理员新增", message)
        self.assertIn("codex&lt;接码&gt;", message)
        self.assertIn("<b>8</b> 个", message)
        self.assertNotIn("codex<接码>", message)

    def test_keyboards_support_language_switching(self) -> None:
        keyboard = main_menu((), "en")
        labels = [
            button.text for row in keyboard.inline_keyboard for button in row
        ]
        language_keyboard = language_menu("en")

        self.assertIn("🌐 Language", labels)
        self.assertIn("📖 Help", labels)
        self.assertEqual(language_keyboard.inline_keyboard[0][1].text, "✅ English")

    def test_group_lottery_public_message_masks_user_identity(self) -> None:
        message = participation_message(
            123456,
            "alice_secret",
            "Alice",
            participant_count=1,
            target_participants=10,
        )

        self.assertIn("@al***et", message)
        self.assertIn("tg://user?id=123456", message)
        self.assertNotIn("alice_secret", message)
        self.assertNotIn("Alice", message)

    def test_group_lottery_public_message_supports_english(self) -> None:
        message = participation_message(
            123456,
            "alice_secret",
            "Alice",
            participant_count=1,
            target_participants=10,
            lang="en",
        )

        self.assertIn("joined successfully", message)
        self.assertIn("Participants", message)


if __name__ == "__main__":
    unittest.main()
