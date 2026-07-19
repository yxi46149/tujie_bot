from __future__ import annotations

import unittest

from app.group_lottery import (
    GROUP_LOTTERY_USAGE,
    parse_duration_seconds,
    parse_group_lottery_command,
)


class GroupLotteryParsingTests(unittest.TestCase):
    def test_parse_timed_points_lottery_from_one_line(self) -> None:
        parsed = parse_group_lottery_command(
            "points 20 3 time 10m 抽奖 群福利积分抽奖"
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.prize_type, "points")
        self.assertEqual(parsed.prize_value, 20)
        self.assertEqual(parsed.winner_count, 3)
        self.assertEqual(parsed.draw_mode, "time")
        self.assertEqual(parsed.trigger_text, "抽奖")
        self.assertEqual(parsed.title, "群福利积分抽奖")
        self.assertIsNotNone(parsed.draw_at)

    def test_parse_count_product_lottery_from_multiline_command(self) -> None:
        parsed = parse_group_lottery_command(
            "product 7 2 count 20\n我要 抽奖\n七夕 群福利卡密抽奖"
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.prize_type, "product")
        self.assertEqual(parsed.prize_value, 7)
        self.assertEqual(parsed.winner_count, 2)
        self.assertEqual(parsed.draw_mode, "count")
        self.assertEqual(parsed.target_participants, 20)
        self.assertEqual(parsed.trigger_text, "我要 抽奖")
        self.assertEqual(parsed.title, "七夕 群福利卡密抽奖")

    def test_rejects_count_lottery_when_target_is_less_than_winners(self) -> None:
        parsed = parse_group_lottery_command(
            "points 20 3 count 2 抽奖 群福利积分抽奖"
        )

        self.assertIsNone(parsed)

    def test_duration_accepts_chinese_and_short_units(self) -> None:
        self.assertEqual(parse_duration_seconds("10m"), 600)
        self.assertEqual(parse_duration_seconds("2小时"), 7200)
        self.assertEqual(parse_duration_seconds("30"), 1800)

    def test_usage_text_is_safe_for_html_parse_mode(self) -> None:
        self.assertIn("&lt;积分&gt;", GROUP_LOTTERY_USAGE)
        self.assertNotIn("<积分>", GROUP_LOTTERY_USAGE)


if __name__ == "__main__":
    unittest.main()
