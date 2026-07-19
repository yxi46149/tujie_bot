from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from math import ceil
from secrets import randbelow
from time import monotonic

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import ChatId, Settings
from app.database import Database
from app.group_lottery import (
    GROUP_LOTTERY_USAGE,
    deliver_group_lottery_result,
    format_draw_at,
    group_lottery_announcement,
    parse_group_lottery_command,
    participation_message,
)
from app.keyboards import lottery_menu, main_menu, product_menu, shop_menu
from app.texts import (
    help_message,
    invite_message,
    invites_message,
    my_cards_message,
    points_message,
    points_rank_message,
    profile,
    rank_message,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MembershipCheck:
    eligible: bool
    missing: tuple[ChatId, ...] = ()
    errors: tuple[ChatId, ...] = ()


@dataclass(frozen=True, slots=True)
class HumanVerifyChallenge:
    question: str
    answer: int
    options: tuple[int, ...]


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


def shuffled_numbers(values: set[int]) -> tuple[int, ...]:
    pool = list(values)
    result: list[int] = []
    while pool:
        result.append(pool.pop(randbelow(len(pool))))
    return tuple(result)


def create_human_verify_challenge() -> HumanVerifyChallenge:
    left = randbelow(8) + 2
    right = randbelow(8) + 1
    if randbelow(2) == 0:
        question = f"{left} + {right}"
        answer = left + right
    else:
        high = max(left, right)
        low = min(left, right)
        question = f"{high} - {low}"
        answer = high - low

    options = {answer}
    while len(options) < 3:
        delta = randbelow(5) + 1
        candidate = answer + delta if randbelow(2) == 0 else answer - delta
        if candidate >= 0:
            options.add(candidate)
    return HumanVerifyChallenge(question, answer, shuffled_numbers(options))


async def check_membership(
    bot: Bot, user_id: int, chat_ids: tuple[ChatId, ...]
) -> MembershipCheck:
    missing: list[ChatId] = []
    errors: list[ChatId] = []
    for chat_id in chat_ids:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        except TelegramRetryAfter as exc:
            logger.warning(
                "成员检查触发 Telegram 限流，chat_id=%s retry_after=%s",
                chat_id,
                exc.retry_after,
            )
            errors.append(chat_id)
            continue
        except TelegramNetworkError:
            logger.warning("成员检查网络异常，chat_id=%s", chat_id)
            errors.append(chat_id)
            continue
        except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError):
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
    reply_markup: InlineKeyboardMarkup | None = None,
    protect_content: bool = False,
) -> None:
    await bot.send_message(
        callback.from_user.id,
        text,
        reply_markup=reply_markup,
        protect_content=protect_content,
    )


def build_router(settings: Settings, db: Database) -> Router:
    root_router = Router(name="points_referral_bot")

    router = Router(name="private_points_referral_bot")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

    verification_attempts: dict[int, float] = {}
    verification_semaphore = asyncio.Semaphore(settings.verify_max_concurrency)

    def is_admin(message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_ids)

    def is_group_chat(message: Message) -> bool:
        return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}

    def is_human_verify_chat(message: Message) -> bool:
        if not settings.human_verify_enabled or not is_group_chat(message):
            return False
        if not settings.human_verify_chat_ids:
            return True
        chat_username = message.chat.username
        chat_handles = {chat_username, f"@{chat_username}"} if chat_username else set()
        for chat_id in settings.human_verify_chat_ids:
            if isinstance(chat_id, int) and chat_id == message.chat.id:
                return True
            if isinstance(chat_id, str) and chat_id in chat_handles:
                return True
        return False

    def muted_permissions() -> ChatPermissions:
        return ChatPermissions(can_send_messages=False)

    def verified_member_permissions() -> ChatPermissions:
        return ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_react_to_messages=True,
        )

    async def unmute_human_verified_member(
        bot: Bot, chat_id: int, user_id: int
    ) -> bool:
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=verified_member_permissions(),
            )
        except TelegramAPIError:
            logger.exception(
                "新人验证通过但解除禁言失败，chat_id=%s user_id=%s",
                chat_id,
                user_id,
            )
            return False
        return True

    def verification_cooldown_remaining(user_id: int) -> int:
        cooldown = settings.verify_cooldown_seconds
        if cooldown <= 0:
            return 0
        now = monotonic()
        last_attempt = verification_attempts.get(user_id)
        if last_attempt is not None and now - last_attempt < cooldown:
            return ceil(cooldown - (now - last_attempt))
        verification_attempts[user_id] = now
        if len(verification_attempts) > 10_000:
            cutoff = now - cooldown
            recent_attempts = {
                key: value
                for key, value in verification_attempts.items()
                if value >= cutoff
            }
            verification_attempts.clear()
            verification_attempts.update(recent_attempts)
        return 0

    def reward_day_window() -> tuple[str, str]:
        local_now = datetime.now(settings.timezone)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(timezone.utc).isoformat(timespec="seconds"),
            local_end.astimezone(timezone.utc).isoformat(timespec="seconds"),
        )

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

    async def render_my_cards(user_id: int) -> str:
        return my_cards_message(await db.get_user_redemptions(user_id))

    async def render_rank() -> str:
        return rank_message(await db.get_rank())

    async def render_points_rank() -> str:
        return points_rank_message(await db.get_points_rank())

    def is_lottery_prize_drawable(prize: object) -> bool:
        if str(prize["prize_type"]) != "product":  # type: ignore[index]
            return True
        return bool(prize["product_is_active"]) and int(prize["stock"] or 0) > 0  # type: ignore[index]

    async def run_checkin(user_id: int) -> str:
        local_date = datetime.now(settings.timezone).date().isoformat()
        outcome = await db.claim_checkin(user_id, local_date, settings.checkin_reward)
        if outcome.claimed:
            return (
                f"✅ 签到成功！+{settings.checkin_reward} 积分\n"
                f"💰 当前积分：<b>{outcome.points}</b>"
            )
        return f"ℹ️ 今天已经签到过了，请明天再来。\n💰 当前积分：<b>{outcome.points}</b>"

    async def render_lottery(user_id: int) -> tuple[str, bool]:
        user = await db.get_user(user_id)
        points = int(user["points"]) if user else 0
        prizes = [
            prize
            for prize in await db.list_lottery_prizes()
            if is_lottery_prize_drawable(prize)
        ]
        lines = [
            "🎲 <b>积分抽奖</b>",
            "",
            f"每次消耗：<b>{settings.lottery_cost}</b> 积分",
            f"当前积分：<b>{points}</b>",
        ]
        if not prizes:
            lines.extend(["", "奖池暂未配置，稍后再来。"])
            return "\n".join(lines), False

        total_weight = sum(int(prize["weight"]) for prize in prizes)
        lines.extend(["", "<b>当前奖池：</b>"])
        for prize in prizes:
            prize_type = str(prize["prize_type"])
            weight = int(prize["weight"])
            chance = weight / total_weight * 100
            if prize_type == "points":
                detail = f"+{int(prize['points_delta'])} 积分"
            elif prize_type == "product":
                detail = f"卡密奖品，库存 {int(prize['stock'] or 0)}"
            else:
                detail = "谢谢参与"
            lines.append(
                f"• {escape(str(prize['name']))}｜{detail}｜约 {chance:.1f}%"
            )
        return "\n".join(lines), True

    async def run_lottery_draw(user_id: int) -> tuple[str, bool]:
        outcome = await db.draw_lottery(user_id, settings.lottery_cost)
        if outcome.status == "no_prizes":
            return "🎲 奖池暂未配置，或卡密奖品暂无库存。", False
        if outcome.status == "insufficient_points":
            return (
                f"❌ 积分不足，本次抽奖需要 <b>{outcome.cost}</b> 积分，"
                f"您当前有 <b>{outcome.points}</b> 积分。"
            ), False
        if outcome.status == "not_registered":
            return "请先发送 /start 创建个人账户后再抽奖。", False
        if outcome.status != "ok":
            return "⚠️ 抽奖失败，请稍后重试。", False

        if outcome.prize_type == "points":
            return (
                "🎉 <b>中奖啦！</b>\n\n"
                f"奖品：{escape(outcome.prize_name)}\n"
                f"获得：<b>{outcome.points_delta}</b> 积分\n"
                f"本次消耗：<b>{outcome.cost}</b> 积分\n"
                f"剩余积分：<b>{outcome.points}</b>"
            ), False
        if outcome.prize_type == "product":
            return (
                "🎉 <b>中奖啦！</b>\n\n"
                f"奖品：{escape(outcome.prize_name)}\n"
                f"卡密：<code>{escape(outcome.code)}</code>\n"
                f"本次消耗：<b>{outcome.cost}</b> 积分\n"
                f"剩余积分：<b>{outcome.points}</b>\n\n"
                "请妥善保存；如发送中断，可使用 /mycards 找回。"
            ), True
        return (
            "😔 <b>很遗憾，本次未中奖</b>\n\n"
            f"奖品：{escape(outcome.prize_name)}\n"
            f"本次消耗：<b>{outcome.cost}</b> 积分\n"
            f"剩余积分：<b>{outcome.points}</b>"
        ), False

    async def run_verification(user_id: int, bot: Bot) -> str:
        if not settings.required_chat_ids:
            return "⚠️ 管理员尚未配置 REQUIRED_CHAT_IDS，暂时无法检查资格。"

        remaining = verification_cooldown_remaining(user_id)
        if remaining:
            return f"⏳ 检查过于频繁，请在 {remaining} 秒后重试。"

        async with verification_semaphore:
            result = await check_membership(bot, user_id, settings.required_chat_ids)
        if result.errors:
            return (
                "⚠️ 暂时无法检查资格。请管理员确认机器人已加入所有指定"
                "群/频道，并拥有查看成员的权限。"
            )
        if result.missing:
            return "❌ 尚未加入全部指定群/频道，请加入后重新点击检查。"

        day_start_utc, day_end_utc = reward_day_window()
        outcome = await db.verify_and_reward(
            user_id,
            settings.invite_reward,
            settings.invite_daily_reward_limit,
            day_start_utc,
            day_end_utc,
        )
        if outcome.rewarded and outcome.inviter_id:
            try:
                await bot.send_message(
                    outcome.inviter_id,
                    "🎉 您邀请的好友已完成资格验证！\n"
                    f"💰 已获得 <b>{outcome.reward_points}</b> 积分。",
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                logger.info("无法通知邀请人 user_id=%s", outcome.inviter_id)
            return "✅ 资格验证通过，邀请人的积分已经结算。"
        if outcome.settled and outcome.limited:
            return "✅ 资格验证通过；邀请人今日奖励已达上限，本次邀请已记录但不再加分。"
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

    async def send_lottery_message(message: Message) -> None:
        if not message.from_user:
            return
        text, has_prizes = await render_lottery(message.from_user.id)
        await message.answer(
            text,
            reply_markup=lottery_menu(settings.lottery_cost, has_prizes),
        )

    async def send_lottery_callback(callback: CallbackQuery, bot: Bot) -> None:
        text, has_prizes = await render_lottery(callback.from_user.id)
        await answer_callback(
            callback,
            bot,
            text,
            reply_markup=lottery_menu(settings.lottery_cost, has_prizes),
        )

    async def handle_group_lottery_participation(
        message: Message, bot: Bot, lottery_id: int
    ) -> None:
        if not message.from_user:
            return
        if settings.required_chat_ids:
            result = await check_membership(
                bot, message.from_user.id, settings.required_chat_ids
            )
            if result.errors:
                await message.reply("暂时无法检查资格，请稍后再试。")
                return
            if result.missing:
                await message.reply("请先加入指定群/频道，再参与抽奖。")
                return

        await ensure_message_user(message)
        outcome = await db.join_group_lottery(
            lottery_id,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
        if outcome.status == "not_found":
            await message.reply("抽奖不存在。")
            return
        if outcome.status == "already_joined":
            return
        if outcome.status == "filled":
            await message.reply("这个抽奖参与人数已满，正在开奖或已结束。")
            return
        if outcome.status != "ok":
            await message.reply("这个抽奖已经结束。")
            return

        feedback = await message.answer(
            participation_message(
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                outcome.participant_count,
                outcome.target_participants,
            )
        )
        await db.set_group_lottery_feedback(lottery_id, feedback.message_id)
        if outcome.previous_feedback_message_id:
            try:
                await bot.delete_message(
                    message.chat.id, outcome.previous_feedback_message_id
                )
            except TelegramAPIError:
                logger.info(
                    "无法删除上一条群抽奖参与反馈，chat_id=%s message_id=%s",
                    message.chat.id,
                    outcome.previous_feedback_message_id,
                )
        if outcome.should_draw:
            await deliver_group_lottery_result(
                bot, db, lottery_id, cancel_on_failure=True
            )

    def group_lotteries_message(rows: list[object]) -> str:
        if not rows:
            return "🎲 当前群没有未开奖的群抽奖。"
        lines = ["🎲 <b>当前群未开奖抽奖</b>", ""]
        for row in rows:
            prize_type = str(row["prize_type"])  # type: ignore[index]
            if prize_type == "points":
                prize = f"{int(row['points_delta'])} 积分"  # type: ignore[index]
            else:
                product_name = row["product_name"] or f"商品 #{row['product_id']}"  # type: ignore[index]
                prize = f"{escape(str(product_name))} 卡密"

            draw_mode = str(row["draw_mode"])  # type: ignore[index]
            participant_count = int(row["participant_count"] or 0)  # type: ignore[index]
            if draw_mode == "count":
                mode = (
                    f"满人 {participant_count}/{int(row['target_participants'])}"  # type: ignore[index]
                )
            elif draw_mode == "time":
                mode = f"定时 {escape(format_draw_at(row['draw_at']))}"  # type: ignore[index]
            else:
                mode = f"手动开奖，已参与 {participant_count}"

            lines.append(
                f"#{row['id']} {escape(str(row['title']))}｜"  # type: ignore[index]
                f"{prize}｜中奖 {int(row['winner_count'])} 人｜{mode}"  # type: ignore[index]
            )
            trigger = str(row["trigger_text"] or "")  # type: ignore[index]
            if trigger:
                lines.append(f"口令：<code>{escape(trigger)}</code>")
        lines.extend(["", "提前开奖：/drawlottery &lt;抽奖编号&gt;"])
        return "\n".join(lines)

    @root_router.message(F.new_chat_members)
    async def human_verify_new_members(message: Message, bot: Bot) -> None:
        if not is_human_verify_chat(message):
            return

        warning_sent = False
        for member in message.new_chat_members or []:
            if member.is_bot:
                continue
            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=settings.human_verify_timeout_seconds)
            ).isoformat(timespec="seconds")
            try:
                await bot.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=member.id,
                    permissions=muted_permissions(),
                )
            except TelegramAPIError:
                logger.exception(
                    "新人验证无法限制成员，chat_id=%s user_id=%s",
                    message.chat.id,
                    member.id,
                )
                if not warning_sent:
                    await message.answer(
                        "⚠️ 新人验证需要机器人拥有“限制成员”权限，请检查群管理员权限。"
                    )
                    warning_sent = True
                continue

            challenge = create_human_verify_challenge()
            token = await db.create_human_verification(
                message.chat.id,
                member.id,
                member.username,
                member.first_name,
                expires_at,
                challenge.answer,
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=str(option),
                            callback_data=(
                                f"humanverify:{member.id}:{token}:{option}"
                            ),
                        )
                        for option in challenge.options
                    ]
                ]
            )
            display_name = escape(member.full_name or member.first_name or "新成员")
            timeout_minutes = max(
                1, ceil(settings.human_verify_timeout_seconds / 60)
            )
            try:
                await message.answer(
                    f'<a href="tg://user?id={member.id}">{display_name}</a> '
                    f"欢迎入群，请在 <b>{timeout_minutes}</b> 分钟内完成验证。\n\n"
                    f"请回答：<b>{escape(challenge.question)}</b> = ?\n"
                    "选择正确答案后会自动解除发言限制。",
                    reply_markup=keyboard,
                )
            except TelegramAPIError:
                logger.exception(
                    "新人验证消息发送失败，chat_id=%s user_id=%s",
                    message.chat.id,
                    member.id,
                )
                await unmute_human_verified_member(bot, message.chat.id, member.id)

        try:
            await message.delete()
        except TelegramAPIError:
            logger.info("无法删除新人入群系统消息，chat_id=%s", message.chat.id)

    @root_router.callback_query(F.data.startswith("humanverify:"))
    async def callback_human_verify(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.message:
            await callback.answer("验证消息已失效。", show_alert=True)
            return
        parts = str(callback.data).split(":", maxsplit=3)
        if len(parts) != 4 or not parts[1].isdigit():
            await callback.answer("验证参数无效。", show_alert=True)
            return
        target_user_id = int(parts[1])
        token = parts[2]
        try:
            selected_answer = int(parts[3])
        except ValueError:
            await callback.answer("验证答案无效。", show_alert=True)
            return
        if callback.from_user.id != target_user_id:
            await callback.answer("这不是你的验证按钮。", show_alert=True)
            return

        chat_id = callback.message.chat.id
        status = await db.complete_human_verification(
            chat_id, target_user_id, token, selected_answer
        )
        if status in {"ok", "already_verified"}:
            if await unmute_human_verified_member(bot, chat_id, target_user_id):
                await callback.answer("验证通过，欢迎入群。", show_alert=True)
                try:
                    await callback.message.delete()
                except TelegramAPIError:
                    await callback.message.edit_text("✅ 人机验证已通过。")
            else:
                await callback.answer(
                    "验证已记录，但机器人缺少解除禁言权限，请联系管理员。",
                    show_alert=True,
                )
            return
        if status == "expired":
            await callback.answer(
                "验证已过期，请联系管理员或重新进群触发验证。",
                show_alert=True,
            )
            return
        if status == "invalid_answer":
            await callback.answer("答案不对，再想一下。", show_alert=True)
            return
        await callback.answer("验证失败，请重新进群触发验证。", show_alert=True)

    @root_router.message(Command("grouplottery"))
    async def command_group_lottery(
        message: Message, command: CommandObject
    ) -> None:
        if not is_group_chat(message):
            await message.answer("请在群聊中发起群抽奖。")
            return
        if not is_admin(message):
            await message.reply("⛔ 只有机器人管理员可以发起群抽奖。")
            return
        if not message.from_user:
            return
        await ensure_message_user(message)

        parsed = parse_group_lottery_command(command.args)
        if parsed is None:
            await message.reply(GROUP_LOTTERY_USAGE)
            return
        outcome = await db.create_group_lottery(
            message.chat.id,
            message.from_user.id,
            parsed.title,
            parsed.prize_type,
            parsed.prize_value,
            parsed.winner_count,
            trigger_text=parsed.trigger_text,
            draw_mode=parsed.draw_mode,
            target_participants=parsed.target_participants,
            draw_at=parsed.draw_at,
        )
        if outcome.status == "invalid":
            await message.reply(GROUP_LOTTERY_USAGE)
            return
        if outcome.status == "duplicate_trigger":
            await message.reply("❌ 当前群已有未开奖抽奖使用相同参与口令。")
            return
        if outcome.status == "product_not_found":
            await message.reply("❌ 商品不存在。")
            return
        if outcome.status == "product_inactive":
            await message.reply("❌ 商品已下架，不能作为群抽奖奖品。")
            return
        if outcome.status == "insufficient_stock":
            await message.reply(
                f"❌ 商品库存不足，当前库存 {outcome.stock}，"
                f"但中奖人数是 {parsed.winner_count}。"
            )
            return
        if outcome.status != "ok" or outcome.lottery_id is None:
            await message.reply("⚠️ 群抽奖创建失败，请稍后重试。")
            return

        sent = await message.answer(
            group_lottery_announcement(
                outcome.lottery_id,
                parsed,
                outcome.product_name,
            )
        )
        await db.set_group_lottery_message(outcome.lottery_id, sent.message_id)

    @root_router.callback_query(F.data.startswith("grouplottery:join:"))
    async def callback_group_lottery_join(
        callback: CallbackQuery, bot: Bot
    ) -> None:
        if not callback.message or callback.message.chat.type == ChatType.PRIVATE:
            await callback.answer("请在群抽奖消息上参与。", show_alert=True)
            return
        try:
            lottery_id = int(str(callback.data).rsplit(":", maxsplit=1)[1])
        except (ValueError, IndexError):
            await callback.answer("抽奖参数无效。", show_alert=True)
            return

        lottery = await db.get_group_lottery(lottery_id)
        if not lottery or int(lottery["chat_id"]) != callback.message.chat.id:
            await callback.answer("这个抽奖不存在或不属于当前群。", show_alert=True)
            return
        if lottery["status"] != "pending":
            await callback.answer("这个抽奖已经结束。", show_alert=True)
            return

        if settings.required_chat_ids:
            result = await check_membership(
                bot, callback.from_user.id, settings.required_chat_ids
            )
            if result.errors:
                await callback.answer(
                    "暂时无法检查资格，请稍后再试。", show_alert=True
                )
                return
            if result.missing:
                await callback.answer(
                    "请先加入指定群/频道，再参与抽奖。", show_alert=True
                )
                return

        await ensure_callback_user(callback)
        outcome = await db.join_group_lottery(
            lottery_id,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
        )
        if outcome.status == "not_found":
            await callback.answer("抽奖不存在。", show_alert=True)
            return
        if outcome.status == "already_joined":
            await callback.answer("你已经参与过了。", show_alert=True)
            return
        if outcome.status == "filled":
            await callback.answer("参与人数已满，正在开奖或已结束。", show_alert=True)
            return
        if outcome.status != "ok":
            await callback.answer("这个抽奖已经结束。", show_alert=True)
            return
        await callback.answer(
            f"参与成功，当前 {outcome.participant_count} 人参与。",
            show_alert=True,
        )
        if outcome.should_draw:
            await deliver_group_lottery_result(
                bot, db, lottery_id, cancel_on_failure=True
            )

    @root_router.message(Command("drawlottery"))
    async def command_draw_group_lottery(
        message: Message, command: CommandObject, bot: Bot
    ) -> None:
        if not is_group_chat(message):
            await message.answer("请在发起抽奖的群聊中开奖。")
            return
        if not is_admin(message):
            await message.reply("⛔ 只有机器人管理员可以开奖。")
            return
        value = (command.args or "").strip()
        if not value.isdigit():
            await message.reply("用法：/drawlottery &lt;抽奖编号&gt;")
            return
        lottery_id = int(value)
        lottery = await db.get_group_lottery(lottery_id)
        if not lottery or int(lottery["chat_id"]) != message.chat.id:
            await message.reply("❌ 这个抽奖不存在或不属于当前群。")
            return
        await deliver_group_lottery_result(bot, db, lottery_id)

    @root_router.message(Command("lotteries"))
    async def command_group_lotteries(message: Message) -> None:
        if not is_group_chat(message):
            await message.answer("请在群聊中查看群抽奖列表。")
            return
        if not is_admin(message):
            await message.reply("⛔ 只有机器人管理员可以查看群抽奖列表。")
            return
        rows = await db.list_pending_group_lotteries(message.chat.id)
        await message.reply(group_lotteries_message(rows))

    @root_router.message(Command("pointrank"))
    async def command_points_rank(message: Message) -> None:
        if message.chat.type not in {
            ChatType.PRIVATE,
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        }:
            return
        await message.answer(await render_points_rank())

    @root_router.message(F.chat.type != ChatType.PRIVATE, F.text)
    async def group_lottery_phrase(message: Message, bot: Bot) -> None:
        text = (message.text or "").strip()
        if not text:
            return
        lottery = await db.get_group_lottery_by_trigger(message.chat.id, text)
        if lottery:
            await handle_group_lottery_participation(message, bot, int(lottery["id"]))
            return
        if text.startswith("/"):
            await message.reply("🔒 为保护积分和卡密，请私聊机器人使用此命令。")

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
            reply_markup=main_menu(settings.join_buttons),
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

    @router.message(Command("lottery"))
    async def command_lottery(message: Message) -> None:
        await ensure_message_user(message)
        await send_lottery_message(message)

    @router.message(Command("mycards"))
    async def command_my_cards(message: Message) -> None:
        if not message.from_user:
            return
        await ensure_message_user(message)
        await message.answer(
            await render_my_cards(message.from_user.id), protect_content=True
        )

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
            reply_markup=main_menu(settings.join_buttons),
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

    @router.callback_query(F.data == "menu:pointrank")
    async def callback_points_rank(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(callback, bot, await render_points_rank())

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

    @router.callback_query(F.data == "menu:lottery")
    async def callback_lottery(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await send_lottery_callback(callback, bot)

    @router.callback_query(F.data == "menu:mycards")
    async def callback_my_cards(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer()
        await ensure_callback_user(callback)
        await answer_callback(
            callback,
            bot,
            await render_my_cards(callback.from_user.id),
            protect_content=True,
        )

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
        intent_token = ""
        if stock > 0:
            intent_token = await db.create_redemption_intent(
                callback.from_user.id,
                product_id,
                settings.redemption_intent_ttl_seconds,
            )
        await answer_callback(
            callback,
            bot,
            "🛒 <b>商品详情</b>\n\n"
            f"名称：<b>{escape(str(product['name']))}</b>\n"
            f"价格：<b>{int(product['points_cost'])}</b> 积分\n"
            f"库存：<b>{stock}</b>\n"
            f"说明：{escape(description)}",
            reply_markup=product_menu(intent_token, has_stock=stock > 0),
        )

    @router.callback_query(F.data.startswith("shop:confirm:"))
    async def callback_redeem(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer("正在兑换…")
        await ensure_callback_user(callback)
        intent_token = str(callback.data).removeprefix("shop:confirm:").strip()
        if not intent_token or len(intent_token) > 40:
            await answer_callback(callback, bot, "⚠️ 商品参数无效。")
            return
        outcome = await db.redeem_card(callback.from_user.id, intent_token)
        if outcome.status in {"invalid_intent", "expired_intent"}:
            text = "⚠️ 兑换确认已失效，请重新打开商城选择商品。"
        elif outcome.status == "not_found":
            text = "⚠️ 商品不存在或已经下架。"
        elif outcome.status == "out_of_stock":
            text = "😔 商品刚刚售罄，积分没有扣除。"
        elif outcome.status == "insufficient_points":
            text = (
                f"❌ 积分不足，需要 <b>{outcome.cost}</b> 积分，"
                f"您当前有 <b>{outcome.points}</b> 积分。"
            )
        elif outcome.status in {"ok", "already_redeemed"}:
            title = (
                "✅ <b>兑换成功</b>"
                if outcome.status == "ok"
                else "ℹ️ <b>该兑换已处理，未重复扣分</b>"
            )
            text = (
                f"{title}\n\n"
                f"商品：{escape(outcome.product_name)}\n"
                f"卡密：<code>{escape(outcome.code)}</code>\n"
                f"剩余积分：<b>{outcome.points}</b>\n\n"
                "请妥善保存；如发送中断，可使用 /mycards 找回。"
            )
            try:
                await answer_callback(callback, bot, text, protect_content=True)
            except TelegramAPIError:
                logger.exception(
                    "卡密消息发送失败，用户可通过 /mycards 找回，user_id=%s",
                    callback.from_user.id,
                )
            return
        else:
            text = "⚠️ 兑换失败，请稍后重试。"
        await answer_callback(callback, bot, text)

    @router.callback_query(F.data == "lottery:draw")
    async def callback_lottery_draw(callback: CallbackQuery, bot: Bot) -> None:
        await callback.answer("正在抽奖…")
        await ensure_callback_user(callback)
        text, protect_content = await run_lottery_draw(callback.from_user.id)
        try:
            await answer_callback(callback, bot, text, protect_content=protect_content)
        except TelegramAPIError:
            logger.exception(
                "抽奖卡密消息发送失败，用户可通过 /mycards 找回，user_id=%s",
                callback.from_user.id,
            )

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
            "/lotteryprizes — 抽奖奖池\n"
            "/addlotteryprize &lt;权重&gt; &lt;类型&gt; ... — 新增抽奖奖品\n"
            "/togglelotteryprize &lt;奖品ID&gt; — 开关抽奖奖品\n"
            "/grouplottery &lt;类型&gt; ... — 在群里发起抽奖\n"
            "/lotteries — 查看当前群未开奖抽奖\n"
            "/drawlottery &lt;抽奖编号&gt; — 在群里开奖\n"
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
            f"兑换次数：{stats['redemptions']}\n"
            f"启用抽奖奖品：{stats['active_lottery_prizes']}\n"
            f"抽奖次数：{stats['lottery_draws']}\n"
            f"群抽奖：{stats['group_lotteries']}\n"
            f"已开奖群抽奖：{stats['drawn_group_lotteries']}"
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
    async def command_add_cards(
        message: Message, command: CommandObject, bot: Bot
    ) -> None:
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
        source_deleted = True
        try:
            await message.delete()
        except TelegramAPIError:
            source_deleted = False
            logger.warning(
                "无法删除包含卡密的管理员消息，message_id=%s", message.message_id
            )
        deletion_warning = (
            "\n⚠️ 原卡密消息未能自动删除，请立即手动删除。" if not source_deleted else ""
        )
        if inserted == -1:
            await bot.send_message(
                message.chat.id, "❌ 商品不存在。" + deletion_warning
            )
        else:
            await bot.send_message(
                message.chat.id,
                f"✅ 成功导入 <b>{inserted}</b> 条新卡密。" + deletion_warning,
            )

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

    @router.message(Command("lotteryprizes"))
    async def command_lottery_prizes(message: Message) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        prizes = await db.list_lottery_prizes(active_only=False)
        if not prizes:
            await message.answer("暂无抽奖奖品。")
            return
        lines = ["🎲 <b>抽奖奖池</b>", ""]
        for prize in prizes:
            state = "启用" if prize["is_active"] else "关闭"
            prize_type = str(prize["prize_type"])
            if prize_type == "points":
                detail = f"积分 +{int(prize['points_delta'])}"
            elif prize_type == "product":
                product_state = "商品上架" if prize["product_is_active"] else "商品下架"
                detail = (
                    f"商品 #{prize['product_id']} "
                    f"{escape(str(prize['product_name'] or '未知商品'))}｜"
                    f"库存 {int(prize['stock'] or 0)}｜{product_state}"
                )
            else:
                detail = "谢谢参与"
            lines.append(
                f"#{prize['id']} {escape(str(prize['name']))}｜"
                f"权重 {prize['weight']}｜{detail}｜{state}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("addlotteryprize"))
    async def command_add_lottery_prize(
        message: Message, command: CommandObject
    ) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        usage = (
            "用法：\n"
            "/addlotteryprize &lt;权重&gt; none &lt;奖品名&gt;\n"
            "/addlotteryprize &lt;权重&gt; points &lt;积分&gt; &lt;奖品名&gt;\n"
            "/addlotteryprize &lt;权重&gt; product &lt;商品ID&gt; &lt;奖品名&gt;"
        )
        parts = (command.args or "").strip().split(maxsplit=3)
        if len(parts) < 3:
            await message.answer(usage)
            return
        try:
            weight = int(parts[0])
        except ValueError:
            await message.answer("权重必须是正整数。")
            return
        if weight <= 0:
            await message.answer("权重必须是正整数。")
            return

        prize_type = parts[1].lower()
        if prize_type == "none":
            name = " ".join(parts[2:]).strip()
            prize_id = await db.add_lottery_prize(name, "none", weight)
        elif prize_type == "points" and len(parts) == 4:
            try:
                points_delta = int(parts[2])
            except ValueError:
                await message.answer("积分奖品的积分数量必须是正整数。")
                return
            prize_id = await db.add_lottery_prize(
                parts[3], "points", weight, points_delta=points_delta
            )
        elif prize_type == "product" and len(parts) == 4:
            try:
                product_id = int(parts[2])
            except ValueError:
                await message.answer("商品 ID 必须是数字。")
                return
            prize_id = await db.add_lottery_prize(
                parts[3], "product", weight, product_id=product_id
            )
        else:
            await message.answer(usage)
            return

        if prize_id is None:
            await message.answer("❌ 奖品创建失败，请检查名称、积分数量或商品 ID。")
        else:
            await message.answer(f"✅ 抽奖奖品已创建，奖品 ID：<code>{prize_id}</code>")

    @router.message(Command("togglelotteryprize"))
    async def command_toggle_lottery_prize(
        message: Message, command: CommandObject
    ) -> None:
        if not is_admin(message):
            await message.answer("⛔ 无管理员权限。")
            return
        value = (command.args or "").strip()
        if not value.isdigit():
            await message.answer("用法：/togglelotteryprize &lt;奖品ID&gt;")
            return
        active = await db.toggle_lottery_prize(int(value))
        if active is None:
            await message.answer("❌ 抽奖奖品不存在。")
        else:
            await message.answer("✅ 抽奖奖品已" + ("启用。" if active else "关闭。"))

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

    @root_router.callback_query(F.message.chat.type != ChatType.PRIVATE)
    async def reject_group_callback(callback: CallbackQuery) -> None:
        await callback.answer(
            "为保护个人信息和卡密，请私聊机器人操作。", show_alert=True
        )

    root_router.include_router(router)
    return root_router
