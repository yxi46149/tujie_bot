from __future__ import annotations

import unittest

from app.group_lottery import participation_message
from app.keyboards import language_menu, main_menu
from app.texts import points_message, points_rank_message, profile


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
