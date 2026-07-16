from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.utils.token import TokenValidationError

from app.config import Settings
from app.database import Database


async def run() -> int:
    try:
        settings = Settings.from_env()
        bot = Bot(settings.bot_token)
        await bot.session.close()
    except (RuntimeError, ValueError, TokenValidationError) as exc:
        print(f"[失败] 配置无效：{exc}")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    if not settings.admin_ids:
        errors.append("ADMIN_IDS 为空，无法使用管理员命令。")
    if not settings.required_chat_ids:
        errors.append("REQUIRED_CHAT_IDS 为空，用户无法完成资格验证。")
    if settings.invite_daily_reward_limit == 0:
        warnings.append("邀请奖励没有每日上限，请确认这是有意配置。")

    database = Database(settings.database_path)
    try:
        await database.initialize()
        integrity = await database.quick_check()
        stats = await database.get_stats()
    except Exception as exc:  # noqa: BLE001 - CLI must turn startup errors into a report
        print(f"[失败] 数据库无法初始化：{exc}")
        return 1

    if integrity != "ok":
        errors.append(f"SQLite quick_check 未通过：{integrity}")

    print("[通过] BOT_TOKEN 格式有效（未连接 Telegram）")
    print(f"[通过] 管理员数量：{len(settings.admin_ids)}")
    print(f"[通过] 必加群/频道数量：{len(settings.required_chat_ids)}")
    print(f"[通过] 时区：{settings.timezone_name}")
    print(f"[通过] 数据库：{settings.database_path}")
    print(
        "[通过] 数据库统计："
        f"用户 {stats['users']}，可用卡密 {stats['available_cards']}，"
        f"兑换 {stats['redemptions']}"
    )

    for warning in warnings:
        print(f"[警告] {warning}")
    for error in errors:
        print(f"[失败] {error}")

    if errors:
        print("自检未通过，请修正以上配置后再启动或发布。")
        return 1
    print("本地配置与数据库自检通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
