from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from app.config import Settings
from app.database import Database
from app.group_lottery import run_group_lottery_scheduler
from app.handlers import build_router
from app.i18n import DEFAULT_LANGUAGE, Language, is_english


def private_commands(lang: Language = DEFAULT_LANGUAGE) -> list[BotCommand]:
    if is_english(lang):
        return [
            BotCommand(command="start", description="Open dashboard"),
            BotCommand(command="points", description="View points"),
            BotCommand(command="verify", description="Verify membership"),
            BotCommand(command="invite", description="Generate invite link"),
            BotCommand(command="myinvites", description="View my invites"),
            BotCommand(command="checkin", description="Daily check-in"),
            BotCommand(command="shop", description="Points shop"),
            BotCommand(command="lottery", description="Points lottery"),
            BotCommand(command="mycards", description="View my card codes"),
            BotCommand(command="pointrank", description="Points ranking"),
            BotCommand(command="rank", description="Invite ranking"),
            BotCommand(command="language", description="Switch language"),
            BotCommand(command="lang", description="Switch language"),
            BotCommand(command="help", description="Help"),
        ]
    return [
        BotCommand(command="start", description="打开个人中心"),
        BotCommand(command="points", description="查看积分"),
        BotCommand(command="verify", description="检查入群资格"),
        BotCommand(command="invite", description="生成邀请入口"),
        BotCommand(command="myinvites", description="查看我的邀请"),
        BotCommand(command="checkin", description="每日签到"),
        BotCommand(command="shop", description="积分商城"),
        BotCommand(command="lottery", description="积分抽奖"),
        BotCommand(command="mycards", description="查看我的卡密"),
        BotCommand(command="pointrank", description="积分排行榜"),
        BotCommand(command="rank", description="邀请排行榜"),
        BotCommand(command="language", description="切换语言"),
        BotCommand(command="lang", description="切换语言"),
        BotCommand(command="help", description="使用说明"),
    ]


def group_commands(lang: Language = DEFAULT_LANGUAGE) -> list[BotCommand]:
    if is_english(lang):
        return [
            BotCommand(command="checkin", description="Daily check-in"),
            BotCommand(command="pointrank", description="Points ranking"),
        ]
    return [
        BotCommand(command="checkin", description="每日签到"),
        BotCommand(command="pointrank", description="积分排行榜"),
    ]


def admin_private_commands(lang: Language = DEFAULT_LANGUAGE) -> list[BotCommand]:
    if is_english(lang):
        return [
            *private_commands(lang),
            BotCommand(command="admin", description="Admin command list"),
            BotCommand(command="stats", description="View bot stats"),
            BotCommand(command="products", description="Products and stock"),
            BotCommand(command="addproduct", description="Create product"),
            BotCommand(command="addcards", description="Add product stock"),
            BotCommand(command="toggleproduct", description="Enable or disable product"),
            BotCommand(command="lotteryprizes", description="Lottery prize pool"),
            BotCommand(command="addlotteryprize", description="Add lottery prize"),
            BotCommand(command="togglelotteryprize", description="Enable or disable prize"),
            BotCommand(command="addpoints", description="Adjust user points"),
        ]
    return [
        *private_commands(lang),
        BotCommand(command="admin", description="管理员命令"),
        BotCommand(command="stats", description="机器人统计"),
        BotCommand(command="products", description="商品与库存"),
        BotCommand(command="addproduct", description="新增商品"),
        BotCommand(command="addcards", description="新增商品库存"),
        BotCommand(command="toggleproduct", description="上架或下架商品"),
        BotCommand(command="lotteryprizes", description="抽奖奖池"),
        BotCommand(command="addlotteryprize", description="新增抽奖奖品"),
        BotCommand(command="togglelotteryprize", description="开关抽奖奖品"),
        BotCommand(command="addpoints", description="调整用户积分"),
    ]


def group_admin_commands(lang: Language = DEFAULT_LANGUAGE) -> list[BotCommand]:
    if is_english(lang):
        return [
            *group_commands(lang),
            BotCommand(command="grouplottery", description="Start group lottery"),
            BotCommand(command="lotteries", description="View group lotteries"),
            BotCommand(command="drawlottery", description="Draw group lottery"),
        ]
    return [
        *group_commands(lang),
        BotCommand(command="grouplottery", description="发起群抽奖"),
        BotCommand(command="lotteries", description="查看群抽奖"),
        BotCommand(command="drawlottery", description="群抽奖开奖"),
    ]


async def set_commands(bot: Bot, admin_ids: frozenset[int] = frozenset()) -> None:
    for lang, language_code in (("zh", None), ("en", "en")):
        commands = private_commands(lang)
        await bot.set_my_commands(
            commands,
            scope=BotCommandScopeDefault(),
            language_code=language_code,
        )
        await bot.set_my_commands(
            commands,
            scope=BotCommandScopeAllPrivateChats(),
            language_code=language_code,
        )
        await bot.set_my_commands(
            group_commands(lang),
            scope=BotCommandScopeAllGroupChats(),
            language_code=language_code,
        )
        await bot.set_my_commands(
            group_admin_commands(lang),
            scope=BotCommandScopeAllChatAdministrators(),
            language_code=language_code,
        )
        admin_commands = admin_private_commands(lang)
        for admin_id in admin_ids:
            await bot.set_my_commands(
                admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
                language_code=language_code,
            )


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
    group_lottery_task = asyncio.create_task(
        run_group_lottery_scheduler(bot, database)
    )

    try:
        await set_commands(bot, settings.admin_ids)
        logging.getLogger(__name__).info(
            "机器人已启动，数据库：%s", settings.database_path
        )
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        group_lottery_task.cancel()
        with suppress(asyncio.CancelledError):
            await group_lottery_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
