from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.config import ChatId, Settings
from app.database import Database
from app.keyboards import main_menu, product_menu, shop_menu
from app.texts import (
    help_message,
    invite_message,
    invites_message,
    points_message,
    profile,
    rank_message,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MembershipCheck:
    eligible: bool
    missing: tuple[ChatId, ...] = ()
    errors: tuple[ChatId, ...] = ()


def parse_inviter(payload: str | None) -> int | None:
    if not payload or not payload.startswith("ref_"):
        return None
    value = payload.removeprefix("ref_")
    return int(value) if value.isdigit() else None


def is_member_status(member: object) -> bool:
    status = getattr(member, "status", None)
    if status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }:
        return True
    return status == ChatMemberStatus.RESTRICTED and bool(
        getattr(member, "is_member", False)
    )


async def check_membership(
    bot: Bot, user_id: int, chat_ids: tuple[ChatId, ...]
) -> MembershipCheck:
    missing: list[ChatId] = []
    errors: list[ChatId] = []
    for chat_id in chat_ids:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.exception("无法检查频道成员身份，chat_id=%s", chat_id)
            errors.append(chat_id)
            continue
        if not is_member_status(member):
            missing.append(chat_id)
    return MembershipCheck(
        eligible=not missing and not errors,
        missing=tuple(missing),
        errors=tuple(errors),
    )


async def answer_callback(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    *,
    reply_markup: object | None = None,
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(text, reply_markup=reply_markup)
    else:
        await bot.send_message(callback.from_user.id, text, reply_markup=reply_markup)


def build_router(settings: Settings, db: Database) -> Router:
    router = Router(name="points_referral_bot")

    async def ensure_message_user(message: Message) -> None:
        if message.from_user:
            await db.register_user(
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
            )

    async def ensure_callback_user(callback: CallbackQuery) -> None:
        await db.register_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
        )

    async def render_profile(user_id: int) -> str:
        user = await db.get_user(user_id)
        points = int(user["points"]) if user else 0
        return profile(user_id, points, settings.invite_reward)

    async def render_points(user_id: int) -> str:
        user = await db.get_user(user_id)
        verified, _ = await db.get_invite_counts(user_id)
        return points_message(int(user["points"]) if user else 0, verified)

    async def render_invite(user_id: int, bot: Bot) -> str:
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user_id}"
        return invite_message(link, settings.invite_reward)

    async def render_my_invites(user_id: int) -> str:
        verified, pending = await db.get_invite_counts(user_id)
        rows = await db.get_recent_invites(user_id)
        return invites_message(verified, pending, rows)

    async def render_rank() -> str:
        return rank_message(await db.get_rank())

    async def run_checkin(user_id: int) -> str:
        local_date = datetime.now(settings.timezone).date().isoformat()
        outcome = await db.claim_checkin(user_id, local_date, settings.checkin_reward)
        if outcome.claimed:
            return (
                f"✅ 签到成功！+{settings.checkin_reward} 积分\n"
                f"💰 当前积分：<b>{outcome.points}</b>"
            )
        return f"ℹ️ 今天已经签到过了，请明天再来。\n💰 当前积分：<b>{outcome.points}</b>"

    async def run_verification(user_id: int, bot: Bot) -> str:
        if not settings.required_chat_ids:
            return "⚠️ 管理员尚未配置 REQUIRED_CHAT_IDS，暂时无法检查资格。"

        result = await check_membership(bot, user_id, settings.required_chat_ids)
        if result.errors:
            return (
                "⚠️ 暂时无法检查资格。请管理员确认机器人已加入所有指定"
                "群/频道，并拥有查看成员的权限。"
            )
        if result.missing:
            return "❌ 尚未加入全部指定群/频道，请加入后重新点击检查。"

        outcome = await db.verify_and_reward(user_id, settings.invite_reward)
        if outcome.rewarded and outcome.inviter_id:
            try:
                await bot.send_message(
                    outcome.inviter_id,
                    "🎉 您邀请的好友已完成资格验证！\n"
                    f"💰 已获得 <b>{settings.invite_reward}</b> 积分。",
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                logger.info("无法通知邀请人 user_id=%s", outcome.inviter_id)
            return "✅ 资格验证通过，邀请人的积分已经结算。"
        return "✅ 资格验证通过！"

    async def send_shop_message(message: Message) -> None:
        products = await db.list_products()
        if not products:
            await message.answer("🛒 商城暂时没有可兑换的商品。")
            return
        await message.answer(
            "🛒 <b>积分商城</b>\n\n请选择要兑换的商品：",
            reply_markup=shop_menu(products),
        )

    async def send_shop_callback(callback: CallbackQuery, bot: Bot) -> None:
        products = await db.list_products()
        if not products:
            await answer_callback(callback, bot, "🛒 商城暂时没有可兑换的商品。")
            return
        await answer_callback(
            callback,
            bot,
            "🛒 <b>积分商城</b>\n\n请选择要兑换的商品：",
            reply_markup=shop_menu(products),
        )

    @router.message(CommandStart())
    async def command_start(message: Message, command: CommandObject) -> None:
        if not message.from_user:
            return
        await db.register_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            inviter_id=parse_inviter(command.args),
        )
        await message.answer(
            await render_profile(message.from_user.id),
            reply_markup=main_menu(settings.required_join_url),
        )

    @router.message(Command("points"))
    async def command_points(message: Message) -> None:
        if not message.from_user:
            return
        await ensure_message_user(message)
        await message.answer(await render_points(message.from_user.id))

    @router.message(Command("verify"))
    async def command_verify(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        await ensure_message_user(message)
        await message.answer(await run_verification(message.from_user.id, bot))

    @router.message(Command("invite"))
    async def command_invite(message: Message, bot: Bot) -> None:
        if not message.from_user:
            return
        await ensure_message_user(message)
        await message.answer(await render_invite(message.from_user.id, bot))

    @router.message(Command("myinvites"))
    async def command_my_invites(message: Message) -> None:
        if not message.from_user:
            return
        await ensure_message_user(message)
        await message.answer(await render_my_invites(message.from_user.id))

    @router.message(Command("checkin"))
    async def command_checkin(message: Message) -> None:
        if not message.from_user:
            return
        await ensure_message_user(message)
        await message.answer(await run_checkin(message.from_user.id))

    @router.message(Command("shop"))
    async def command_shop(message: Message) -> None:
        await ensure_message_user(message)
        await send_shop_message(message)

    @router.message(Command("rank"))
    async def command_rank(message: Message) -> None:
        await ensure_message_user(message)
        await message.answer(await render_rank())

    @router.message(Command("help"))
    async def command_help(message: Message) -> None:
        await ensure_message_user(message)
        await message.answer(
            help_message(settings.invite_reward, settings.checkin_reward)
        )

    @router.callback_query(F.data == "menu:verify")
    async def callback_verify(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer("正在检查资格…")
        await ensure_callback_user(callback)
        await answer_callback(
            callback,
            bot,
            await run_verification(callback.from_user.id, bot),
            reply_markup=main_menu(settings.required_join_url),
        )

    @router.callback_query(F.data == "menu:points")
    async def callback_points(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(callback, bot, await render_points(callback.from_user.id))

    @router.callback_query(F.data == "menu:checkin")
    async def callback_checkin(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(callback, bot, await run_checkin(callback.from_user.id))

    @router.callback_query(F.data == "menu:invite")
    async def callback_invite(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(
            callback, bot, await render_invite(callback.from_user.id, bot)
        )

    @router.callback_query(F.data == "menu:myinvites")
    async def callback_my_invites(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(
            callback, bot, await render_my_invites(callback.from_user.id)
        )

    @router.callback_query(F.data == "menu:rank")
    async def callback_rank(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(callback, bot, await render_rank())

    @router.callback_query(F.data == "menu:help")
    async def callback_help(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(
            callback,
            bot,
            help_message(settings.invite_reward, settings.checkin_reward),
        )

    @router.callback_query(F.data == "menu:shop")
    async def callback_shop(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await send_shop_callback(callback, bot)

    @router.callback_query(F.data.startswith("shop:view:"))
    async def callback_product(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        try:
            product_id = int(str(callback.data).rsplit(":", maxsplit=1)[1])
        except (ValueError, IndexError):
            await answer_callback(callback, bot, "⚠️ 商品参数无效，请重新打开商城。")
            return
        product = await db.get_product(product_id)
        if not product or not product["is_active"]:
            await answer_callback(callback, bot, "⚠️ 商品不存在或已经下架。")
            return
        stock = int(product["stock"] or 0)
        description = str(product["description"] or "暂无说明")
        await answer_callback(
            callback,
            bot,
            "🛒 <b>商品详情</b>\n\n"
            f"名称：<b>{escape(str(product['name']))}</b>\n"
            f"价格：<b>{int(product['points_cost'])}</b> 积分\n"
            f"库存：<b>{stock}</b>\n"
            f"说明：{escape(description)}",
            reply_markup=product_menu(product_id, has_stock=stock > 0),
        )

    @router.callback_query(F.data.startswith("shop:confirm:"))
    async def callback_redeem(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer("正在兑换…")
        await ensure_callback_user(callback)
        try:
            product_id = int(str(callback.data).rsplit(":", maxsplit=1)[1])
        except (ValueError, IndexError):
            await answer_callback(callback, bot, "⚠️ 商品参数无效。")
            return
        outcome = await db.redeem_card(callback.from_user.id, product_id)
        if outcome.status == "not_found":
            text = "⚠️ 商品不存在或已经下架。"
        elif outcome.status == "out_of_stock":
            text = "😔 商品刚刚售罄，积分没有扣除。"
        elif outcome.status == "insufficient_points":
            text = (
                f"❌ 积分不足，需要 <b>{outcome.cost}</b> 积分，"
                f"您当前有 <b>{outcome.points}</b> 积分。"
            )
        else:
            text = (
                "✅ <b>兑换成功</b>\n\n"
                f"商品：{escape(outcome.product_name)}\n"
                f"卡密：<code>{escape(outcome.code)}</code>\n"
                f"剩余积分：<b>{outcome.points}</b>\n\n"
                "请妥善保存卡密，本消息不会在群聊中发送。"
            )
        await answer_callback(callback, bot, text)

    def is_admin(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_ids)

    @router.message(Command("admin"))
    async def command_admin(message: Message) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        await message.answer(
            "🛠 <b>管理员命令</b>\n\n"
            "/stats — 统计数据\n"
            "/products — 商品与库存\n"
            "/addproduct &lt;积分&gt; &lt;名称&gt; — 新增商品\n"
            "/addcards &lt;商品ID&gt; 后换行粘贴卡密 — 导入卡密\n"
            "/toggleproduct &lt;商品ID&gt; — 上架/下架\n"
            "/addpoints &lt;用户ID&gt; &lt;数量&gt; — 调整积分"
        )

    @router.message(Command("stats"))
    async def command_stats(message: Message) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        stats = await db.get_stats()
        await message.answer(
            "📊 <b>机器人统计</b>\n\n"
            f"用户：{stats['users']}\n"
            f"已验证用户：{stats['verified_users']}\n"
            f"已结算邀请：{stats['verified_referrals']}\n"
            f"可用卡密：{stats['available_cards']}\n"
            f"兑换次数：{stats['redemptions']}"
        )

    @router.message(Command("products"))
    async def command_products(message: Message) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        products = await db.list_products(active_only=False)
        if not products:
            await message.answer("暂无商品。")
            return
        lines = ["🛒 <b>商品与库存</b>", ""]
        for product in products:
            state = "上架" if product["is_active"] else "下架"
            lines.append(
                f"#{product['id']} {escape(str(product['name']))}｜"
                f"{product['points_cost']} 积分｜库存 {int(product['stock'] or 0)}｜{state}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("addproduct"))
    async def command_add_product(message: Message, command: CommandObject) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) <= 0:
            await message.answer("用法：/addproduct &lt;所需积分&gt; &lt;商品名称&gt;")
            return
        product_id = await db.add_product(parts[1].strip(), int(parts[0]))
        await message.answer(f"✅ 商品已创建，商品 ID：<code>{product_id}</code>")

    @router.message(Command("addcards"))
    async def command_add_cards(message: Message, command: CommandObject) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        lines = (command.args or "").splitlines()
        if not lines:
            await message.answer(
                "用法：第一行 /addcards &lt;商品ID&gt;，随后每行一条卡密。"
            )
            return
        first_line = lines[0].strip().split(maxsplit=1)
        if not first_line or not first_line[0].isdigit():
            await message.answer("商品 ID 必须是数字。")
            return
        codes: list[str] = []
        if len(first_line) == 2:
            codes.append(first_line[1])
        codes.extend(lines[1:])
        if not any(code.strip() for code in codes):
            await message.answer("请至少提供一条卡密，每行一条。")
            return
        inserted = await db.add_cards(int(first_line[0]), codes)
        if inserted == -1:
            await message.answer("❌ 商品不存在。")
        else:
            await message.answer(f"✅ 成功导入 <b>{inserted}</b> 条新卡密。")

    @router.message(Command("toggleproduct"))
    async def command_toggle_product(message: Message, command: CommandObject) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        value = (command.args or "").strip()
        if not value.isdigit():
            await message.answer("用法：/toggleproduct &lt;商品ID&gt;")
            return
        active = await db.toggle_product(int(value))
        if active is None:
            await message.answer("❌ 商品不存在。")
        else:
            await message.answer("✅ 商品已" + ("上架。" if active else "下架。"))

    @router.message(Command("addpoints"))
    async def command_add_points(message: Message, command: CommandObject) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        parts = (command.args or "").strip().split()
        if len(parts) != 2:
            await message.answer(
                "用法：/addpoints &lt;用户ID&gt; &lt;数量，可为负数&gt;"
            )
            return
        try:
            user_id, delta = int(parts[0]), int(parts[1])
        except ValueError:
            await message.answer("用户 ID 和积分数量必须是整数。")
            return
        points = await db.adjust_points(
            user_id, delta, reason=f"admin_adjustment:{message.from_user.id}"
        )
        if points is None:
            await message.answer("❌ 用户不存在，或扣减后积分会小于 0。")
        else:
            await message.answer(f"✅ 调整成功，用户当前积分：<b>{points}</b>")

    @router.message(F.text.startswith("/"))
    async def unknown_command(message: Message) -> None:
        await message.answer("未知命令。发送 /help 查看使用说明。")

    @router.callback_query()
    async def unknown_callback(callback: CallbackQuery) -> None:
        await callback.answer("按钮已失效，请发送 /start 刷新菜单。", show_alert=True)

    return router
