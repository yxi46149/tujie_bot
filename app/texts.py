from __future__ import annotations

from html import escape
from typing import Sequence

from app.i18n import DEFAULT_LANGUAGE, Language, is_english
from app.privacy import masked_public_name


def profile(
    user_id: int,
    points: int,
    invite_reward: int,
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if is_english(lang):
        return (
            "🤖 <b>Dashboard</b>\n"
            f"🆔 Your ID: <code>{user_id}</code>\n"
            f"💰 Available points: <b>{points}</b>\n\n"
            "----------------------------------------\n"
            "📖 <b>Commands:</b>\n"
            "1️⃣ Dashboard: /start\n"
            "2️⃣ Points: /points\n"
            "3️⃣ Verify membership: /verify\n"
            "4️⃣ Invite link: /invite\n"
            "5️⃣ My invites: /myinvites\n"
            "6️⃣ Daily check-in: /checkin\n"
            "7️⃣ Points shop: /shop\n"
            "8️⃣ Points lottery: /lottery\n"
            "9️⃣ Points ranking: /pointrank\n"
            "🔟 Invite ranking: /rank\n"
            "🎟 My card codes: /mycards\n"
            "🌐 Language: /language\n"
            "----------------------------------------\n"
            "⚠️ Invite friends to join the required groups/channels and pass /verify. "
            f"You will receive <b>{invite_reward}</b> points."
        )
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
        "7️⃣ 积分商城：/shop\n"
        "8️⃣ 积分抽奖：/lottery\n"
        "9️⃣ 积分排行：/pointrank\n"
        "🔟 邀请排行：/rank\n"
        "🎟 我的卡密：/mycards\n"
        "🌐 语言切换：/language\n"
        "----------------------------------------\n"
        "⚠️ 邀请好友加入指定群/频道并通过 /verify 后，"
        f"您将获得 <b>{invite_reward}</b> 积分。"
    )


def help_message(
    invite_reward: int,
    checkin_reward: int,
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if is_english(lang):
        return (
            "📖 <b>Help</b>\n\n"
            "• /start /points - View dashboard and points\n"
            "• /verify - Check required group/channel membership\n"
            "• /invite - Generate your invite link\n"
            "• /myinvites - View invited users and settlement status\n"
            "• /checkin - Claim daily check-in points\n"
            "• /shop - Points shop\n"
            "• /lottery - Spend points on lottery draws\n"
            "• /mycards - Recover redeemed card codes\n"
            "• /pointrank - Points ranking\n"
            "• /rank - Invite ranking\n"
            "• /language - Switch language\n\n"
            f"💡 Each verified invite gives +{invite_reward} points; "
            f"daily check-in gives +{checkin_reward} points."
        )
    return (
        "📖 <b>使用说明</b>\n\n"
        "• /start /points —— 查看个人中心与积分\n"
        "• /verify —— 加入指定群/频道后检查资格，并为邀请人结算积分\n"
        "• /invite —— 生成你的专属邀请链接\n"
        "• /myinvites —— 查看自己邀请的人和结算状态\n"
        "• /checkin —— 每日签到领积分\n"
        "• /shop —— 积分商城\n"
        "• /lottery —— 消耗积分参与抽奖\n"
        "• /mycards —— 查看已兑换卡密，发送失败时也可找回\n"
        "• /pointrank —— 查看积分排行榜\n"
        "• /rank —— 查看邀请排行榜\n"
        "• /language —— 切换中英文\n\n"
        f"💡 每邀请 1 位好友完成验证 +{invite_reward} 积分；"
        f"每日签到 +{checkin_reward} 积分。"
    )


def points_message(
    points: int,
    verified_invites: int,
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if is_english(lang):
        return (
            f"💰 Available points: <b>{points}</b>\n"
            f"👥 Verified invites: <b>{verified_invites}</b>"
        )
    return (
        f"💰 当前可用积分：<b>{points}</b>\n👥 成功邀请：<b>{verified_invites}</b> 人"
    )


def invite_message(
    link: str,
    reward: int,
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if is_english(lang):
        return (
            "🔗 <b>Your Invite Link</b>\n\n"
            "Share this invite text with friends:\n\n"
            f"<code>{escape(invite_copy_text(link, lang))}</code>\n\n"
            "After your friend starts the bot through this link and passes /verify, "
            f"you will receive <b>{reward}</b> points.\n"
            "Tap the button below to copy the invite text."
        )
    return (
        "🔗 <b>您的专属邀请入口</b>\n\n"
        "把下面这段发给好友：\n\n"
        f"<code>{escape(invite_copy_text(link, lang))}</code>\n\n"
        "好友通过该入口启动机器人并完成 /verify 后，"
        f"您可获得 <b>{reward}</b> 积分。\n"
        "点击下方按钮可一键复制邀请文案。"
    )


def invite_copy_text(link: str, lang: Language = DEFAULT_LANGUAGE) -> str:
    if is_english(lang):
        return f"{link}\nCheck in to claim a Codex card code."
    return f"{link}\n签到即可领取codex接码CDK"


def stock_added_message(product_name: str, count: int) -> str:
    return f"📦 管理员新增 <b>{escape(product_name)}</b> 商品库存 <b>{count}</b> 个。"


def invites_message(
    verified: int,
    pending: int,
    rows: Sequence[object],
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if is_english(lang):
        lines = [
            "👥 <b>My Invites</b>",
            "",
            f"✅ Verified: <b>{verified}</b>",
            f"⏳ Pending: <b>{pending}</b>",
        ]
        settled_text = "✅ Settled"
        pending_text = "⏳ Pending"
        recent_title = "<b>Recent invites:</b>"
        fallback_name = "User"
    else:
        lines = [
            "👥 <b>我的邀请</b>",
            "",
            f"✅ 已完成验证：<b>{verified}</b> 人",
            f"⏳ 待完成验证：<b>{pending}</b> 人",
        ]
        settled_text = "✅ 已结算"
        pending_text = "⏳ 待验证"
        recent_title = "<b>最近邀请：</b>"
        fallback_name = "用户"
    if rows:
        lines.extend(["", recent_title])
        for row in rows:
            username = row["username"]  # type: ignore[index]
            first_name = str(row["first_name"] or fallback_name)  # type: ignore[index]
            display = f"@{username}" if username else first_name
            status = settled_text if row["status"] == "verified" else pending_text  # type: ignore[index]
            lines.append(f"• {escape(display)} - {status}")
    return "\n".join(lines)


def rank_message(rows: Sequence[object], lang: Language = DEFAULT_LANGUAGE) -> str:
    if not rows:
        if is_english(lang):
            return "🏆 <b>Invite Ranking</b>\n\nNo verified invites yet."
        return "🏆 <b>邀请排行榜</b>\n\n暂时还没有已完成验证的邀请。"
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Invite Ranking</b>" if is_english(lang) else "🏆 <b>邀请排行榜</b>", ""]
    unit = "invites" if is_english(lang) else "人"
    fallback_name = "User" if is_english(lang) else "用户"
    for index, row in enumerate(rows, start=1):
        username = row["username"]  # type: ignore[index]
        first_name = str(row["first_name"] or fallback_name)  # type: ignore[index]
        display = f"@{username}" if username else first_name
        prefix = medals[index - 1] if index <= 3 else f"{index}."
        lines.append(
            f"{prefix} {escape(display)} - <b>{int(row['invite_count'])}</b> {unit}"  # type: ignore[index]
        )
    return "\n".join(lines)


def points_rank_message(
    rows: Sequence[object],
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if not rows:
        if is_english(lang):
            return "💎 <b>Points Ranking</b>\n\nNo users have points yet."
        return "💎 <b>积分排行榜</b>\n\n暂时还没有用户拥有积分。"
    medals = ["🥇", "🥈", "🥉"]
    lines = ["💎 <b>Points Ranking</b>" if is_english(lang) else "💎 <b>积分排行榜</b>", ""]
    unit = "points" if is_english(lang) else "积分"
    for index, row in enumerate(rows, start=1):
        username = row["username"]  # type: ignore[index]
        first_name = row["first_name"]  # type: ignore[index]
        display = masked_public_name(username, first_name)
        prefix = medals[index - 1] if index <= 3 else f"{index}."
        lines.append(
            f"{prefix} {escape(display)} - <b>{int(row['points'])}</b> {unit}"  # type: ignore[index]
        )
    return "\n".join(lines)


def my_cards_message(
    rows: Sequence[object],
    lang: Language = DEFAULT_LANGUAGE,
) -> str:
    if not rows:
        if is_english(lang):
            return "🎟 <b>My Card Codes</b>\n\nYou do not have any redemption records yet."
        return "🎟 <b>我的卡密</b>\n\n您还没有兑换记录。"
    lines = (
        [
            "🎟 <b>My Card Codes</b>",
            "",
            "Here are your latest 10 redemption records. Keep them safe:",
            "",
        ]
        if is_english(lang)
        else [
            "🎟 <b>我的卡密</b>",
            "",
            "以下为最近 10 条兑换记录，请妥善保存：",
            "",
        ]
    )
    for row in rows:
        lines.extend(
            [
                f"• <b>{escape(str(row['product_name']))}</b>",  # type: ignore[index]
                f"  <code>{escape(str(row['code']))}</code>",  # type: ignore[index]
                f"  {escape(str(row['created_at']))}",  # type: ignore[index]
            ]
        )
    return "\n".join(lines)
