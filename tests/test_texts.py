from __future__ import annotations

import unittest

from app.group_lottery import participation_message
from app.texts import points_rank_message


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


if __name__ == "__main__":
    unittest.main()
