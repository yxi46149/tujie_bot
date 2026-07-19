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


GROUP_LOTTERY_USAGE = (
    "用法：\n"
    "/grouplottery points &lt;积分&gt; &lt;中奖人数&gt; time &lt;时长&gt; &lt;参与口令&gt; &lt;标题&gt;\n"
    "/grouplottery product &lt;商品ID&gt; &lt;中奖人数&gt; count &lt;参与人数&gt; &lt;参与口令&gt; &lt;标题&gt;\n\n"
    "示例：\n"
    "/grouplottery points 20 3 time 10m 抽奖 群福利积分抽奖\n"
    "/grouplottery product 1 1 count 50 抽卡 群福利卡密抽奖\n\n"
    "也可以换行写：\n"
    "/grouplottery points 20 3 time 10m\n"
    "抽奖\n"
    "群福利积分抽奖"
)


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
    if len(lines) >= 3:
        first_line_parts = lines[0].split()
        if len(first_line_parts) == 5:
            parts = [*first_line_parts, lines[1], "\n".join(lines[2:])]
        else:
            parts = args.strip().split(maxsplit=6)
    else:
        parts = args.strip().split(maxsplit=6)

    if len(parts) != 7:
        return None

    prize_type = parts[0].lower()
    draw_mode = normalize_draw_mode(parts[3])
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
    )


def normalize_draw_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"time", "timed", "timer", "delay", "定时"}:
        return "time"
    if normalized in {"count", "people", "participants", "人数", "满人"}:
        return "count"
    return None


def display_user(user_id: int, username: str | None, first_name: str | None) -> str:
    if username:
        return f"@{escape(username)}"
    return f'<a href="tg://user?id={user_id}">{escape(first_name or "用户")}</a>'


def prize_label(prize_type: str, prize_value: int, product_name: str = "") -> str:
    if prize_type == "points":
        return f"{prize_value} 积分"
    if product_name:
        return f"{escape(product_name)} 卡密"
    return f"商品 #{prize_value} 卡密"


def format_draw_at(value: str | None) -> str:
    if not value:
        return "待定"
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
) -> str:
    if parsed.draw_mode == "time":
        mode = f"定时开奖：<code>{escape(format_draw_at(parsed.draw_at))}</code>"
    else:
        mode = f"满 <b>{parsed.target_participants}</b> 人自动开奖"
    return (
        "🎉 <b>群抽奖已开启</b>\n\n"
        f"编号：<code>{lottery_id}</code>\n"
        f"标题：<b>{escape(parsed.title)}</b>\n"
        f"奖品：<b>{prize_label(parsed.prize_type, parsed.prize_value, product_name)}</b>\n"
        f"中奖人数：<b>{parsed.winner_count}</b>\n"
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
) -> str:
    count_text = (
        f"{participant_count}/{target_participants}"
        if target_participants is not None
        else str(participant_count)
    )
    return (
        f"✅ {display_user(user_id, username, first_name)} 参与成功\n"
        f"当前参与人数：<b>{count_text}</b>"
    )


async def deliver_group_lottery_result(
    bot: Bot,
    db: Database,
    lottery_id: int,
    *,
    cancel_on_failure: bool = False,
) -> GroupLotteryDrawOutcome:
    lottery = await db.get_group_lottery(lottery_id)
    if not lottery:
        return GroupLotteryDrawOutcome(status="not_found")

    chat_id = int(lottery["chat_id"])
    outcome = await db.draw_group_lottery(lottery_id)
    if outcome.status == "ok":
        failed_private_messages = await send_winner_private_messages(bot, outcome)
        await bot.send_message(
            chat_id,
            group_lottery_result_message(
                lottery_id, outcome, failed_private_messages
            ),
        )
        return outcome

    if outcome.status in {"no_participants", "product_inactive", "insufficient_stock"}:
        if cancel_on_failure:
            await db.cancel_group_lottery(lottery_id)
        await bot.send_message(
            chat_id,
            group_lottery_failure_message(lottery_id, outcome, cancelled=cancel_on_failure),
        )
    elif outcome.status == "drawn":
        await bot.send_message(chat_id, f"🎲 抽奖 <code>{lottery_id}</code> 已经开奖。")
    elif outcome.status == "cancelled":
        await bot.send_message(chat_id, f"🎲 抽奖 <code>{lottery_id}</code> 已取消。")
    return outcome


async def send_winner_private_messages(
    bot: Bot, outcome: GroupLotteryDrawOutcome
) -> list[str]:
    failed_private_messages: list[str] = []
    for winner in outcome.winners:
        if winner.prize_type == "product":
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
                await bot.send_message(
                    winner.user_id,
                    "🎉 <b>群抽奖中奖啦！</b>\n\n"
                    f"抽奖：{escape(outcome.title)}\n"
                    f"奖品：<b>{winner.points_delta}</b> 积分，已到账。",
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                logger.info("无法通知群抽奖中奖者 user_id=%s", winner.user_id)
    return failed_private_messages


def group_lottery_result_message(
    lottery_id: int,
    outcome: GroupLotteryDrawOutcome,
    failed_private_messages: list[str] | None = None,
) -> str:
    winner_lines = [
        display_user(winner.user_id, winner.username, winner.first_name)
        for winner in outcome.winners
    ]
    result_lines = [
        "🎊 <b>群抽奖已开奖</b>",
        "",
        f"编号：<code>{lottery_id}</code>",
        f"标题：<b>{escape(outcome.title)}</b>",
        f"参与人数：<b>{outcome.participant_count}</b>",
        f"奖品：<b>{escape(outcome.prize_name)}</b>",
        "",
        "<b>中奖用户：</b>",
        *[f"• {line}" for line in winner_lines],
    ]
    if outcome.prize_type == "product":
        result_lines.extend(
            [
                "",
                "卡密已私聊发送；未收到的中奖用户请先私聊机器人，然后发送 /mycards 找回。",
            ]
        )
    if failed_private_messages:
        result_lines.extend(
            [
                "",
                "以下用户尚未开启私聊，需主动私聊机器人兑奖：",
                *[f"• {line}" for line in failed_private_messages],
            ]
        )
    return "\n".join(result_lines)


def group_lottery_failure_message(
    lottery_id: int, outcome: GroupLotteryDrawOutcome, *, cancelled: bool
) -> str:
    suffix = "本次抽奖已取消。" if cancelled else "请稍后再开奖。"
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
