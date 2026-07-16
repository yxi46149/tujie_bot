from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.config import Settings
from app.database import Database
from app.handlers import build_router


async def set_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="打开个人中心"),
        BotCommand(command="points", description="查看积分"),
        BotCommand(command="verify", description="检查入群资格"),
        BotCommand(command="invite", description="生成邀请入口"),
        BotCommand(command="myinvites", description="查看我的邀请"),
        BotCommand(command="checkin", description="每日签到"),
        BotCommand(command="shop", description="兑换卡密"),
        BotCommand(command="mycards", description="查看我的卡密"),
        BotCommand(command="rank", description="邀请排行榜"),
        BotCommand(command="help", description="使用说明"),
    ]
    await bot.set_my_commands(commands)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    settings = Settings.from_env()
    database = Database(settings.database_path)
    await database.initialize()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, database))

    try:
        await set_commands(bot)
        logging.getLogger(__name__).info(
            "机器人已启动，数据库：%s", settings.database_path
        )
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
