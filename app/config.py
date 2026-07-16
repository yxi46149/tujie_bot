from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


ChatId = int | str


def _parse_int_set(value: str) -> frozenset[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            result.add(int(item))
    return frozenset(result)


def _parse_chat_ids(value: str) -> tuple[ChatId, ...]:
    result: list[ChatId] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if item.lstrip("-").isdigit():
            result.append(int(item))
        else:
            result.append(item)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    required_chat_ids: tuple[ChatId, ...]
    required_join_url: str
    invite_reward: int
    checkin_reward: int
    timezone_name: str
    database_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "缺少 BOT_TOKEN，请复制 .env.example 为 .env 后填写机器人令牌。"
            )

        database_value = os.getenv("DATABASE_PATH", "data/bot.db").strip()
        database_path = Path(database_value)
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path

        invite_reward = int(os.getenv("INVITE_REWARD", "5"))
        checkin_reward = int(os.getenv("CHECKIN_REWARD", "1"))
        if invite_reward < 0 or checkin_reward < 0:
            raise RuntimeError("INVITE_REWARD 和 CHECKIN_REWARD 不能为负数。")

        timezone_name = os.getenv("TIMEZONE", "Asia/Shanghai").strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(f"无法识别时区：{timezone_name}") from exc

        return cls(
            bot_token=token,
            admin_ids=_parse_int_set(os.getenv("ADMIN_IDS", "")),
            required_chat_ids=_parse_chat_ids(os.getenv("REQUIRED_CHAT_IDS", "")),
            required_join_url=os.getenv("REQUIRED_JOIN_URL", "").strip(),
            invite_reward=invite_reward,
            checkin_reward=checkin_reward,
            timezone_name=timezone_name,
            database_path=database_path,
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)
