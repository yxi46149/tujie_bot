from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(join_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if join_url:
        rows.append([InlineKeyboardButton(text="➡️ 加入通知频道", url=join_url)])
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="✅ 我已加入，检查资格", callback_data="menu:verify"
                )
            ],
            [
                InlineKeyboardButton(text="💰 查看积分", callback_data="menu:points"),
                InlineKeyboardButton(text="📅 每日签到", callback_data="menu:checkin"),
            ],
            [
                InlineKeyboardButton(
                    text="🔗 生成邀请入口", callback_data="menu:invite"
                ),
                InlineKeyboardButton(
                    text="👥 我的邀请", callback_data="menu:myinvites"
                ),
            ],
            [
                InlineKeyboardButton(text="🛒 兑换卡密", callback_data="menu:shop"),
                InlineKeyboardButton(text="🏆 邀请排行榜", callback_data="menu:rank"),
            ],
            [InlineKeyboardButton(text="📖 使用说明", callback_data="menu:help")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_menu(products: Sequence[object]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        product_id = int(product["id"])  # type: ignore[index]
        name = str(product["name"])  # type: ignore[index]
        cost = int(product["points_cost"])  # type: ignore[index]
        stock = int(product["stock"] or 0)  # type: ignore[index]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{name}｜{cost} 积分｜库存 {stock}",
                    callback_data=f"shop:view:{product_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_menu(product_id: int, has_stock: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_stock:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ 确认兑换", callback_data=f"shop:confirm:{product_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ 返回商城", callback_data="menu:shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
