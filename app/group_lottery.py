from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)

from app.database import Database, GroupLotteryDrawOutcome, utc_now
from app.i18n import DEFAULT_LANGUAGE, Language, is_english
from app.privacy import masked_user_link


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedGroupLotteryCommand:
    prize_type: str
    prize_value: int
    winner_count: int
    draw_mode: str
    trigger_text: str
    title: str
    target_participants: int | None = None
    draw_at: str | None = None
    entry_cost: int = 0


GROUP_LOTTERY_USAGE = (
    "用法：\n"
    "/grouplottery points &lt;积分&gt; &lt;中奖人数&gt; time &lt;时长&gt; &lt;参与口令&gt; &lt;标题&gt;\n"
    "/grouplottery product &lt;商品ID&gt; &lt;中奖人数&gt; count &lt;参与人数&gt; &lt;参与口令&gt; &lt;标题&gt;\n"
    "/grouplottery product &lt;商品ID&gt; &lt;中奖人数&gt; time &lt;时长&gt; cost &lt;报名积分&gt; &lt;参与口令&gt; &lt;标题&gt;\n\n"
    "示例：\n"
    "/grouplottery points 20 3 time 10m 抽奖 群福利积分抽奖\n"
    "/grouplottery product 1 1 count 50 抽卡 群福利卡密抽奖\n"
    "/grouplottery product 1 5 time 10m cost 2 兔姐666 codex接码CDK\n\n"
    "也可以换行写：\n"
    "/grouplottery points 20 3 time 10m\n"
    "抽奖\n"
    "群福利积分抽奖"
)

GROUP_LOTTERY_USAGE_EN = (
    "Usage:\n"
    "/grouplottery points &lt;points&gt; &lt;winners&gt; time &lt;duration&gt; &lt;trigger&gt; &lt;title&gt;\n"
    "/grouplottery product &lt;product_id&gt; &lt;winners&gt; count &lt;participants&gt; &lt;trigger&gt; &lt;title&gt;\n"
    "/grouplottery product &lt;product_id&gt; &lt;winners&gt; time &lt;duration&gt; cost &lt;entry_points&gt; &lt;trigger&gt; &lt;title&gt;\n\n"
    "Examples:\n"
    "/grouplottery points 20 3 time 10m draw Group points giveaway\n"
    "/grouplottery product 1 1 count 50 card Group card-code giveaway\n"
    "/grouplottery product 1 5 time 10m cost 2 lucky Group card-code giveaway\n\n"
    "Multi-line format is also supported:\n"
    "/grouplottery points 20 3 time 10m\n"
    "draw\n"
    "Group points giveaway"
)


def group_lottery_usage(lang: Language = DEFAULT_LANGUAGE) -> str:
    return GROUP_LOTTERY_USAGE_EN if is_english(lang) else GROUP_LOTTERY_USAGE


def parse_duration_seconds(raw_value: str) -> int | None:
    value = raw_value.strip().lower()
    if not value:
        return None
    units = (
        ("分钟", 60),
        ("小时", 60 * 60),
        ("天", 24 * 60 * 60),
        ("秒", 1),
        ("min", 60),
        ("m", 60),
        ("h", 60 * 60),
        ("d", 24 * 60 * 60),
        ("s", 1),
    )
    for suffix, factor in units:
        if value.endswith(suffix):
            number = value[: -len(suffix)].strip()
            return int(number) * factor if number.isdigit() else None
    return int(value) * 60 if value.isdigit() else None


def parse_group_lottery_command(args: str | None) -> ParsedGroupLotteryCommand | None:
    if not args or not args.strip():
        return None
    lines = [line.strip() for line in args.strip().splitlines() if line.strip()]
    fee_keywords = {"cost", "fee", "entry", "积分", "报名费", "扣分"}

    def has_fee_keyword(parts: list[str]) -> bool:
        return len(parts) == 7 and parts[5].strip().lower() in fee_keywords

    if len(lines) >= 3:
        first_line_parts = lines[0].split()
        if len(first_line_parts) in {5, 7}:
            parts = [*first_line_parts, lines[1], "\n".join(lines[2:])]
        else:
            preview_parts = args.strip().split(maxsplit=6)
            if has_fee_keyword(preview_parts):
                parts = args.strip().split(maxsplit=8)
            else:
                parts = preview_parts
    else:
        preview_parts = args.strip().split(maxsplit=6)
        if has_fee_keyword(preview_parts):
            parts = args.strip().split(maxsplit=8)
        else:
            parts = preview_parts

    if len(parts) not in {7, 9}:
        return None

    prize_type = parts[0].lower()
    draw_mode = normalize_draw_mode(parts[3])
    entry_cost = 0
    if len(parts) == 9:
        fee_keyword = parts[5].strip().lower()
        if fee_keyword not in fee_keywords:
            return None
        try:
            entry_cost = int(parts[6])
        except ValueError:
            return None
        if entry_cost < 0:
            return None
        trigger_text = parts[7].strip()
        title = parts[8].strip()
    else:
        trigger_text = parts[5].strip()
        title = parts[6].strip()
    if prize_type not in {"points", "product"} or draw_mode is None:
        return None
    if not trigger_text or not title:
        return None

    try:
        prize_value = int(parts[1])
        winner_count = int(parts[2])
    except ValueError:
        return None
    if prize_value <= 0 or winner_count <= 0:
        return None

    if draw_mode == "time":
        seconds = parse_duration_seconds(parts[4])
        if seconds is None or seconds <= 0:
            return None
        draw_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
            timespec="seconds"
        )
        return ParsedGroupLotteryCommand(
            prize_type=prize_type,
            prize_value=prize_value,
            winner_count=winner_count,
            draw_mode=draw_mode,
            trigger_text=trigger_text,
            title=title,
            draw_at=draw_at,
            entry_cost=entry_cost,
        )

    try:
        target_participants = int(parts[4])
    except ValueError:
        return None
    if target_participants < winner_count:
        return None
    return ParsedGroupLotteryCommand(
        prize_type=prize_type,
        prize_value=prize_value,
        winner_count=winner_count,
        draw_mode=draw_mode,
        trigger_text=trigger_text,
        title=title,
        target_participants=target_participants,
        entry_cost=entry_cost,
    )


def normalize_draw_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"time", "timed", "timer", "delay", "定时"}:
        return "time"
    if normalized in {"count", "people", "participants", "人数", "满人"}:
        return "count"
    return None


def display_user(user_id: int, username: str | None, first_name: str | None) -> str:
    return masked_user_link(user_id, username, first_name)


def prize_label(
    prize_type: str,
    prize_value: int,
    product_name: str = "",
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if prize_type == "points":
        return f"{prize_value} points" if is_english(lang) else f"{prize_value} 积分"
    if product_name:
        return (
            f"{escape(product_name)} card code"
            if is_english(lang)
            else f"{escape(product_name)} 卡密"
        )
    if is_english(lang):
        return f"Product #{prize_value} card code"
    return f"商品 #{prize_value} 卡密"


def format_draw_at(value: str | None, lang: Language = DEFAULT_LANGUAGE) -> str:
    if not value:
        return "TBD" if is_english(lang) else "待定"
    try:
        draw_at = datetime.fromisoformat(value)
    except ValueError:
        return value
    beijing = draw_at.astimezone(timezone(timedelta(hours=8)))
    return beijing.strftime("%Y-%m-%d %H:%M:%S UTC+8")


def group_lottery_announcement(
    lottery_id: int,
    parsed: ParsedGroupLotteryCommand,
    product_name: str = "",
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if parsed.draw_mode == "time":
        if is_english(lang):
            mode = (
                "Draw time: "
                f"<code>{escape(format_draw_at(parsed.draw_at, lang))}</code>"
            )
        else:
            mode = (
                "定时开奖："
                f"<code>{escape(format_draw_at(parsed.draw_at, lang))}</code>"
            )
    else:
        mode = (
            f"Auto draw at <b>{parsed.target_participants}</b> participants"
            if is_english(lang)
            else f"满 <b>{parsed.target_participants}</b> 人自动开奖"
        )
    entry_text = (
        f"Entry cost: <b>{parsed.entry_cost}</b> points\n"
        if is_english(lang) and parsed.entry_cost > 0
        else f"报名消耗：<b>{parsed.entry_cost}</b> 积分\n"
        if parsed.entry_cost > 0
        else ""
    )
    if is_english(lang):
        return (
            "🎉 <b>Group Lottery Started</b>\n\n"
            f"ID: <code>{lottery_id}</code>\n"
            f"Title: <b>{escape(parsed.title)}</b>\n"
            "Prize: "
            f"<b>{prize_label(parsed.prize_type, parsed.prize_value, product_name, lang)}</b>\n"
            f"Winners: <b>{parsed.winner_count}</b>\n"
            f"{entry_text}"
            f"{mode}\n\n"
            f"Trigger phrase: <code>{escape(parsed.trigger_text)}</code>\n"
            "Send the exact phrase in this group to join."
        )
    return (
        "🎉 <b>群抽奖已开启</b>\n\n"
        f"编号：<code>{lottery_id}</code>\n"
        f"标题：<b>{escape(parsed.title)}</b>\n"
        "奖品："
        f"<b>{prize_label(parsed.prize_type, parsed.prize_value, product_name, lang)}</b>\n"
        f"中奖人数：<b>{parsed.winner_count}</b>\n"
        f"{entry_text}"
        f"{mode}\n\n"
        f"参与口令：<code>{escape(parsed.trigger_text)}</code>\n"
        "在本群发送完全一致的口令即可参与。"
    )


def participation_message(
    user_id: int,
    username: str | None,
    first_name: str | None,
    participant_count: int,
    target_participants: int | None,
    lang: Language = DEFAULT_LANGUAGE,
    entry_cost: int = 0,
    points: int | None = None,
) -> str:
    count_text = (
        f"{participant_count}/{target_participants}"
        if target_participants is not None
        else str(participant_count)
    )
    if is_english(lang):
        fee_lines = []
        if entry_cost > 0:
            fee_lines.append(f"Entry cost: <b>{entry_cost}</b> points")
            if points is not None:
                fee_lines.append(f"Remaining points: <b>{points}</b>")
        return (
            f"✅ {display_user(user_id, username, first_name)} joined successfully\n"
            f"Participants: <b>{count_text}</b>"
            + (("\n" + "\n".join(fee_lines)) if fee_lines else "")
        )
    fee_lines = []
    if entry_cost > 0:
        fee_lines.append(f"报名消耗：<b>{entry_cost}</b> 积分")
        if points is not None:
            fee_lines.append(f"剩余积分：<b>{points}</b>")
    return (
        f"✅ {display_user(user_id, username, first_name)} 参与成功\n"
        f"当前参与人数：<b>{count_text}</b>"
        + (("\n" + "\n".join(fee_lines)) if fee_lines else "")
    )


async def deliver_group_lottery_result(
    bot: Bot,
    db: Database,
    lottery_id: int,
    *,
    cancel_on_failure: bool = False,
    lang: Language = DEFAULT_LANGUAGE,
) -> GroupLotteryDrawOutcome:
    lottery = await db.get_group_lottery(lottery_id)
    if not lottery:
        return GroupLotteryDrawOutcome(status="not_found")

    chat_id = int(lottery["chat_id"])
    outcome = await db.draw_group_lottery(lottery_id)
    if outcome.status == "ok":
        failed_private_messages = await send_winner_private_messages(bot, db, outcome)
        await bot.send_message(
            chat_id,
            group_lottery_result_message(
                lottery_id, outcome, failed_private_messages, lang
            ),
        )
        return outcome

    if outcome.status in {"no_participants", "product_inactive", "insufficient_stock"}:
        if cancel_on_failure:
            await db.cancel_group_lottery(lottery_id)
        await bot.send_message(
            chat_id,
            group_lottery_failure_message(
                lottery_id, outcome, cancelled=cancel_on_failure, lang=lang
            ),
        )
    elif outcome.status == "drawn":
        await bot.send_message(
            chat_id,
            (
                f"🎲 Lottery <code>{lottery_id}</code> has already been drawn."
                if is_english(lang)
                else f"🎲 抽奖 <code>{lottery_id}</code> 已经开奖。"
            ),
        )
    elif outcome.status == "cancelled":
        await bot.send_message(
            chat_id,
            (
                f"🎲 Lottery <code>{lottery_id}</code> has been cancelled."
                if is_english(lang)
                else f"🎲 抽奖 <code>{lottery_id}</code> 已取消。"
            ),
        )
    return outcome


async def send_winner_private_messages(
    bot: Bot, db: Database, outcome: GroupLotteryDrawOutcome
) -> list[str]:
    failed_private_messages: list[str] = []
    for winner in outcome.winners:
        lang = await db.get_user_language(winner.user_id)
        if winner.prize_type == "product":
            if is_english(lang):
                text = (
                    "🎉 <b>You won the group lottery!</b>\n\n"
                    f"Lottery: {escape(outcome.title)}\n"
                    f"Prize: {escape(winner.prize_name)}\n"
                    f"Card code: <code>{escape(winner.code)}</code>\n\n"
                    "Keep it safe. If delivery is interrupted, use /mycards to recover it."
                )
            else:
                text = (
                    "🎉 <b>群抽奖中奖啦！</b>\n\n"
                    f"抽奖：{escape(outcome.title)}\n"
                    f"奖品：{escape(winner.prize_name)}\n"
                    f"卡密：<code>{escape(winner.code)}</code>\n\n"
                    "请妥善保存；如发送中断，可使用 /mycards 找回。"
                )
            try:
                await bot.send_message(winner.user_id, text, protect_content=True)
            except (TelegramBadRequest, TelegramForbiddenError):
                failed_private_messages.append(
                    display_user(winner.user_id, winner.username, winner.first_name)
                )
        elif winner.prize_type == "points":
            try:
                if is_english(lang):
                    text = (
                        "🎉 <b>You won the group lottery!</b>\n\n"
                        f"Lottery: {escape(outcome.title)}\n"
                        f"Prize: <b>{winner.points_delta}</b> points have been credited."
                    )
                else:
                    text = (
                        "🎉 <b>群抽奖中奖啦！</b>\n\n"
                        f"抽奖：{escape(outcome.title)}\n"
                        f"奖品：<b>{winner.points_delta}</b> 积分，已到账。"
                    )
                await bot.send_message(winner.user_id, text)
            except (TelegramBadRequest, TelegramForbiddenError):
                logger.info("无法通知群抽奖中奖者 user_id=%s", winner.user_id)
    return failed_private_messages


def group_lottery_result_message(
    lottery_id: int,
    outcome: GroupLotteryDrawOutcome,
    failed_private_messages: list[str] | None = None,
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    winner_lines = [
        display_user(winner.user_id, winner.username, winner.first_name)
        for winner in outcome.winners
    ]
    if is_english(lang):
        result_lines = [
            "🎊 <b>Group Lottery Drawn</b>",
            "",
            f"ID: <code>{lottery_id}</code>",
            f"Title: <b>{escape(outcome.title)}</b>",
            f"Participants: <b>{outcome.participant_count}</b>",
            f"Prize: <b>{escape(outcome.prize_name)}</b>",
        ]
        if outcome.entry_cost > 0:
            result_lines.append(f"Entry cost: <b>{outcome.entry_cost}</b> points")
        result_lines.extend(
            [
                "",
                "<b>Winners:</b>",
                *[f"• {line}" for line in winner_lines],
            ]
        )
    else:
        result_lines = [
            "🎊 <b>群抽奖已开奖</b>",
            "",
            f"编号：<code>{lottery_id}</code>",
            f"标题：<b>{escape(outcome.title)}</b>",
            f"参与人数：<b>{outcome.participant_count}</b>",
            f"奖品：<b>{escape(outcome.prize_name)}</b>",
        ]
        if outcome.entry_cost > 0:
            result_lines.append(f"报名消耗：<b>{outcome.entry_cost}</b> 积分")
        result_lines.extend(
            [
                "",
                "<b>中奖用户：</b>",
                *[f"• {line}" for line in winner_lines],
            ]
        )
    if outcome.prize_type == "product":
        result_lines.extend(
            [
                "",
                (
                    "Card codes were sent by private message. If you did not receive one, "
                    "open a private chat with the bot and send /mycards."
                    if is_english(lang)
                    else "卡密已私聊发送；未收到的中奖用户请先私聊机器人，然后发送 /mycards 找回。"
                ),
            ]
        )
    if failed_private_messages:
        result_lines.extend(
            [
                "",
                (
                    "These users have not opened a private chat with the bot yet:"
                    if is_english(lang)
                    else "以下用户尚未开启私聊，需主动私聊机器人兑奖："
                ),
                *[f"• {line}" for line in failed_private_messages],
            ]
        )
    return "\n".join(result_lines)


def group_lottery_failure_message(
    lottery_id: int,
    outcome: GroupLotteryDrawOutcome,
    *,
    cancelled: bool,
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if is_english(lang):
        suffix = "This lottery has been cancelled." if cancelled else "Please draw it later."
        if cancelled and outcome.entry_cost > 0:
            suffix += " Entry fees have been refunded."
        if outcome.status == "no_participants":
            return f"🎲 Lottery <code>{lottery_id}</code> has no participants. {suffix}"
        if outcome.status == "product_inactive":
            return f"🎲 Lottery <code>{lottery_id}</code>'s prize product is inactive. {suffix}"
        if outcome.status == "insufficient_stock":
            return (
                f"🎲 Lottery <code>{lottery_id}</code> does not have enough prize stock. "
                f"Current stock {outcome.stock}, required {outcome.winner_count}. {suffix}"
            )
        return f"🎲 Lottery <code>{lottery_id}</code> cannot be drawn now. {suffix}"
    suffix = "本次抽奖已取消。" if cancelled else "请稍后再开奖。"
    if cancelled and outcome.entry_cost > 0:
        suffix += " 报名积分已退回。"
    if outcome.status == "no_participants":
        return f"🎲 抽奖 <code>{lottery_id}</code> 没有人参与，{suffix}"
    if outcome.status == "product_inactive":
        return f"🎲 抽奖 <code>{lottery_id}</code> 的奖品商品已下架，{suffix}"
    if outcome.status == "insufficient_stock":
        return (
            f"🎲 抽奖 <code>{lottery_id}</code> 奖品库存不足，"
            f"当前库存 {outcome.stock}，需要 {outcome.winner_count}，{suffix}"
        )
    return f"🎲 抽奖 <code>{lottery_id}</code> 暂时无法开奖，{suffix}"


async def run_group_lottery_scheduler(
    bot: Bot,
    db: Database,
    *,
    interval_seconds: int = 5,
) -> None:
    while True:
        for lottery in await db.list_due_group_lotteries(utc_now()):
            try:
                await deliver_group_lottery_result(
                    bot, db, int(lottery["id"]), cancel_on_failure=True
                )
            except TelegramAPIError:
                logger.exception("定时群抽奖开奖失败，lottery_id=%s", lottery["id"])
            except Exception:
                logger.exception("定时群抽奖任务异常，lottery_id=%s", lottery["id"])
        await asyncio.sleep(interval_seconds)
