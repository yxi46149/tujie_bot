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


def _parse_strings(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_bool(value: str, *, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    raise ValueError(f"无法识别布尔配置：{value}")


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    required_chat_ids: tuple[ChatId, ...]
    required_join_urls: tuple[str, ...]
    required_chat_names: tuple[str, ...]
    invite_reward: int
    invite_daily_reward_limit: int
    checkin_reward: int
    lottery_cost: int
    verify_cooldown_seconds: int
    verify_max_concurrency: int
    redemption_intent_ttl_seconds: int
    human_verify_enabled: bool
    human_verify_chat_ids: tuple[ChatId, ...]
    human_verify_timeout_seconds: int
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

        required_chat_ids = _parse_chat_ids(os.getenv("REQUIRED_CHAT_IDS", ""))
        required_join_urls = _parse_strings(os.getenv("REQUIRED_JOIN_URLS", ""))
        legacy_join_url = os.getenv("REQUIRED_JOIN_URL", "").strip()
        if not required_join_urls and legacy_join_url:
            required_join_urls = (legacy_join_url,)
        required_chat_names = _parse_strings(os.getenv("REQUIRED_CHAT_NAMES", ""))
        if len(required_join_urls) != len(required_chat_ids):
            raise RuntimeError(
                "REQUIRED_JOIN_URLS 的数量必须与 REQUIRED_CHAT_IDS 完全一致。"
            )
        if required_chat_names and len(required_chat_names) != len(required_chat_ids):
            raise RuntimeError(
                "REQUIRED_CHAT_NAMES 的数量必须与 REQUIRED_CHAT_IDS 完全一致。"
            )
        if required_chat_ids and not required_chat_names:
            required_chat_names = tuple(
                f"指定群/频道 {index}" for index in range(1, len(required_chat_ids) + 1)
            )

        invite_reward = int(os.getenv("INVITE_REWARD", "5"))
        invite_daily_reward_limit = int(os.getenv("INVITE_DAILY_REWARD_LIMIT", "20"))
        checkin_reward = int(os.getenv("CHECKIN_REWARD", "1"))
        lottery_cost = int(os.getenv("LOTTERY_COST", "5"))
        verify_cooldown_seconds = int(os.getenv("VERIFY_COOLDOWN_SECONDS", "15"))
        verify_max_concurrency = int(os.getenv("VERIFY_MAX_CONCURRENCY", "5"))
        redemption_intent_ttl_seconds = int(
            os.getenv("REDEMPTION_INTENT_TTL_SECONDS", "600")
        )
        human_verify_enabled = _parse_bool(os.getenv("HUMAN_VERIFY_ENABLED", "false"))
        human_verify_chat_ids = _parse_chat_ids(os.getenv("HUMAN_VERIFY_CHAT_IDS", ""))
        human_verify_timeout_seconds = int(
            os.getenv("HUMAN_VERIFY_TIMEOUT_SECONDS", "300")
        )
        if (
            min(
                invite_reward,
                invite_daily_reward_limit,
                checkin_reward,
                lottery_cost,
                verify_cooldown_seconds,
                human_verify_timeout_seconds,
            )
            < 0
        ):
            raise RuntimeError("积分、每日上限、冷却时间和验证超时时间不能为负数。")
        if lottery_cost <= 0:
            raise RuntimeError("LOTTERY_COST 必须大于 0。")
        if verify_max_concurrency < 1:
            raise RuntimeError("VERIFY_MAX_CONCURRENCY 必须大于 0。")
        if redemption_intent_ttl_seconds < 60:
            raise RuntimeError("REDEMPTION_INTENT_TTL_SECONDS 不能小于 60。")
        if human_verify_enabled and human_verify_timeout_seconds < 30:
            raise RuntimeError("HUMAN_VERIFY_TIMEOUT_SECONDS 不能小于 30。")

        timezone_name = os.getenv("TIMEZONE", "Asia/Shanghai").strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(f"无法识别时区：{timezone_name}") from exc

        return cls(
            bot_token=token,
            admin_ids=_parse_int_set(os.getenv("ADMIN_IDS", "")),
            required_chat_ids=required_chat_ids,
            required_join_urls=required_join_urls,
            required_chat_names=required_chat_names,
            invite_reward=invite_reward,
            invite_daily_reward_limit=invite_daily_reward_limit,
            checkin_reward=checkin_reward,
            lottery_cost=lottery_cost,
            verify_cooldown_seconds=verify_cooldown_seconds,
            verify_max_concurrency=verify_max_concurrency,
            redemption_intent_ttl_seconds=redemption_intent_ttl_seconds,
            human_verify_enabled=human_verify_enabled,
            human_verify_chat_ids=human_verify_chat_ids,
            human_verify_timeout_seconds=human_verify_timeout_seconds,
            timezone_name=timezone_name,
            database_path=database_path,
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def join_buttons(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            zip(self.required_chat_names, self.required_join_urls, strict=True)
        )
