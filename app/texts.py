from __future__ import annotations

from html import escape
from typing import Sequence


def profile(user_id: int, points: int, invite_reward: int) -> str:
    return (
        "🤖 <b>个人中心</b>\n"
        f"🆔 您的专属 ID：<code>{user_id}</code>\n"
        f"💰 当前可用积分：<b>{points}</b>\n\n"
        "----------------------------------------\n"
        "📖 <b>操作指南：</b>\n"
        "1️⃣ 打开个人中心：/start\n"
        "2️⃣ 查询积分：/points\n"
        "3️⃣ 检查资格：/verify\n"
        "4️⃣ 推广邀请：/invite\n"
        "5️⃣ 我的邀请：/myinvites\n"
        "6️⃣ 每日签到：/checkin\n"
        "7️⃣ 兑换卡密：/shop\n"
        "8️⃣ 积分抽奖：/lottery\n"
        "9️⃣ 邀请排行：/rank\n"
        "🔟 我的卡密：/mycards\n"
        "----------------------------------------\n"
        "⚠️ 邀请好友加入指定群/频道并通过 /verify 后，"
        f"您将获得 <b>{invite_reward}</b> 积分。"
    )


def help_message(invite_reward: int, checkin_reward: int) -> str:
    return (
        "📖 <b>使用说明</b>\n\n"
        "• /start /points —— 查看个人中心与积分\n"
        "• /verify —— 加入指定群/频道后检查资格，并为邀请人结算积分\n"
        "• /invite —— 生成你的专属邀请链接\n"
        "• /myinvites —— 查看自己邀请的人和结算状态\n"
        "• /checkin —— 每日签到领积分\n"
        "• /shop —— 用积分兑换卡密\n"
        "• /lottery —— 消耗积分参与抽奖\n"
        "• /mycards —— 查看已兑换卡密，发送失败时也可找回\n"
        "• /rank —— 查看邀请排行榜\n\n"
        f"💡 每邀请 1 位好友完成验证 +{invite_reward} 积分；"
        f"每日签到 +{checkin_reward} 积分。"
    )


def points_message(points: int, verified_invites: int) -> str:
    return (
        f"💰 当前可用积分：<b>{points}</b>\n👥 成功邀请：<b>{verified_invites}</b> 人"
    )


def invite_message(link: str, reward: int) -> str:
    return (
        "🔗 <b>您的专属邀请入口</b>\n\n"
        f"<code>{escape(link)}</code>\n\n"
        "好友必须通过此链接启动机器人，并完成 /verify，"
        f"您才会获得 <b>{reward}</b> 积分。"
    )


def invites_message(verified: int, pending: int, rows: Sequence[object]) -> str:
    lines = [
        "👥 <b>我的邀请</b>",
        "",
        f"✅ 已完成验证：<b>{verified}</b> 人",
        f"⏳ 待完成验证：<b>{pending}</b> 人",
    ]
    if rows:
        lines.extend(["", "<b>最近邀请：</b>"])
        for row in rows:
            username = row["username"]  # type: ignore[index]
            first_name = str(row["first_name"] or "用户")  # type: ignore[index]
            display = f"@{username}" if username else first_name
            status = "✅ 已结算" if row["status"] == "verified" else "⏳ 待验证"  # type: ignore[index]
            lines.append(f"• {escape(display)} — {status}")
    return "\n".join(lines)


def rank_message(rows: Sequence[object]) -> str:
    if not rows:
        return "🏆 <b>邀请排行榜</b>\n\n暂时还没有已完成验证的邀请。"
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>邀请排行榜</b>", ""]
    for index, row in enumerate(rows, start=1):
        username = row["username"]  # type: ignore[index]
        first_name = str(row["first_name"] or "用户")  # type: ignore[index]
        display = f"@{username}" if username else first_name
        prefix = medals[index - 1] if index <= 3 else f"{index}."
        lines.append(
            f"{prefix} {escape(display)} — <b>{int(row['invite_count'])}</b> 人"  # type: ignore[index]
        )
    return "\n".join(lines)


def my_cards_message(rows: Sequence[object]) -> str:
    if not rows:
        return "🎟 <b>我的卡密</b>\n\n您还没有兑换记录。"
    lines = [
        "🎟 <b>我的卡密</b>",
        "",
        "以下为最近 10 条兑换记录，请妥善保存：",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"• <b>{escape(str(row['product_name']))}</b>",  # type: ignore[index]
                f"  <code>{escape(str(row['code']))}</code>",  # type: ignore[index]
                f"  {escape(str(row['created_at']))}",  # type: ignore[index]
            ]
        )
    return "\n".join(lines)
