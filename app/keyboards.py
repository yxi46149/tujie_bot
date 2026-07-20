from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.i18n import DEFAULT_LANGUAGE, Language, is_english


def main_menu(
    join_buttons: Sequence[tuple[str, str]],
    lang: Language = DEFAULT_LANGUAGE,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    english = is_english(lang)
    for label, url in join_buttons:
        text = f"➡️ Join {label}" if english else f"➡️ 加入{label}"
        rows.append([InlineKeyboardButton(text=text, url=url)])
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text=(
                        "✅ I joined, verify"
                        if english
                        else "✅ 我已加入，检查资格"
                    ),
                    callback_data="menu:verify",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Points" if english else "💰 查看积分",
                    callback_data="menu:points",
                ),
                InlineKeyboardButton(
                    text="📅 Check in" if english else "📅 每日签到",
                    callback_data="menu:checkin",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 Invite link" if english else "🔗 生成邀请入口",
                    callback_data="menu:invite",
                ),
                InlineKeyboardButton(
                    text="👥 My invites" if english else "👥 我的邀请",
                    callback_data="menu:myinvites",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🛒 Points shop" if english else "🛒 积分商城",
                    callback_data="menu:shop",
                ),
                InlineKeyboardButton(
                    text="🎟 My cards" if english else "🎟 我的卡密",
                    callback_data="menu:mycards",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎲 Points lottery" if english else "🎲 积分抽奖",
                    callback_data="menu:lottery",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💎 Points ranking" if english else "💎 积分排行榜",
                    callback_data="menu:pointrank",
                ),
                InlineKeyboardButton(
                    text="🏆 Invite ranking" if english else "🏆 邀请排行榜",
                    callback_data="menu:rank",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Language" if english else "🌐 语言切换",
                    callback_data="menu:language",
                ),
                InlineKeyboardButton(
                    text="📖 Help" if english else "📖 使用说明",
                    callback_data="menu:help",
                ),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def language_menu(current_language: Language = DEFAULT_LANGUAGE) -> InlineKeyboardMarkup:
    current_is_english = is_english(current_language)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=("中文" if current_is_english else "✅ 中文"),
                    callback_data="language:set:zh",
                ),
                InlineKeyboardButton(
                    text=("✅ English" if current_is_english else "English"),
                    callback_data="language:set:en",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back" if current_is_english else "⬅️ 返回",
                    callback_data="menu:start",
                )
            ],
        ]
    )


def shop_menu(
    products: Sequence[object],
    lang: Language = DEFAULT_LANGUAGE,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    english = is_english(lang)
    for product in products:
        product_id = int(product["id"])  # type: ignore[index]
        name = str(product["name"])  # type: ignore[index]
        cost = int(product["points_cost"])  # type: ignore[index]
        stock = int(product["stock"] or 0)  # type: ignore[index]
        text = (
            f"{name} | {cost} pts | stock {stock}"
            if english
            else f"{name}｜{cost} 积分｜库存 {stock}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"shop:view:{product_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_menu(
    intent_token: str,
    has_stock: bool,
    lang: Language = DEFAULT_LANGUAGE,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    english = is_english(lang)
    if has_stock:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Confirm" if english else "✅ 确认兑换",
                    callback_data=f"shop:confirm:{intent_token}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Back to shop" if english else "⬅️ 返回商城",
                callback_data="menu:shop",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lottery_menu(
    cost: int,
    has_prizes: bool,
    lang: Language = DEFAULT_LANGUAGE,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    english = is_english(lang)
    if has_prizes:
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"🎲 Draw once for {cost} points"
                        if english
                        else f"🎲 消耗 {cost} 积分抽一次"
                    ),
                    callback_data="lottery:draw",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="💰 View points" if english else "💰 查看积分",
                callback_data="menu:points",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
