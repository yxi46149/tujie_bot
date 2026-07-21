from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.token import TokenValidationError

from app.config import Settings


def can_receive_stock_notice(membership: object) -> bool:
    status = getattr(membership, "status", None)
    if status in {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.MEMBER,
    }:
        return True
    return status == ChatMemberStatus.RESTRICTED and bool(
        getattr(membership, "is_member", False)
    )


async def run() -> int:
    try:
        settings = Settings.from_env()
        bot = Bot(settings.bot_token)
    except (RuntimeError, ValueError, TokenValidationError) as exc:
        print(f"[失败] 配置无效：{exc}")
        return 1

    errors: list[str] = []
    try:
        try:
            me = await bot.get_me()
        except TelegramAPIError as exc:
            print(f"[失败] 无法连接 Telegram 或 Token 无效：{exc}")
            return 1

        print(f"[通过] 已连接机器人：@{me.username}（ID {me.id}）")
        if not settings.required_chat_ids:
            errors.append("未配置 REQUIRED_CHAT_IDS。")

        for index, chat_id in enumerate(settings.required_chat_ids, start=1):
            label = settings.required_chat_names[index - 1]
            try:
                chat = await bot.get_chat(chat_id)
                membership = await bot.get_chat_member(chat_id, me.id)
            except TelegramAPIError as exc:
                errors.append(f"{label}（{chat_id}）无法访问：{exc}")
                continue

            if membership.status not in {
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            }:
                errors.append(
                    f"{label}（{chat_id}）中机器人不是管理员，"
                    "成员资格检查可能失败。"
                )
                continue
            print(
                f"[通过] {label}：{chat.title or chat_id}，"
                f"机器人状态 {membership.status}"
            )

        if settings.human_verify_enabled:
            if not settings.human_verify_chat_ids:
                print("[警告] 新人验证已启用但未指定 HUMAN_VERIFY_CHAT_IDS，所有群都会尝试验证。")
            for chat_id in settings.human_verify_chat_ids:
                try:
                    chat = await bot.get_chat(chat_id)
                    membership = await bot.get_chat_member(chat_id, me.id)
                except TelegramAPIError as exc:
                    errors.append(f"新人验证群（{chat_id}）无法访问：{exc}")
                    continue
                if membership.status not in {
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.CREATOR,
                }:
                    errors.append(f"新人验证群（{chat_id}）中机器人不是管理员。")
                    continue
                if not bool(getattr(membership, "can_restrict_members", False)):
                    errors.append(
                        f"新人验证群（{chat_id}）中机器人缺少“限制成员/移除成员”权限。"
                    )
                    continue
                if not bool(getattr(membership, "can_delete_messages", False)):
                    errors.append(
                        f"新人验证群（{chat_id}）中机器人缺少“删除消息”权限。"
                    )
                    continue
                print(
                    f"[通过] 新人验证群：{chat.title or chat_id}，"
                    "机器人具备限制成员/移除成员/删除消息权限"
                )

        for chat_id in settings.stock_notify_chat_ids:
            try:
                chat = await bot.get_chat(chat_id)
                membership = await bot.get_chat_member(chat_id, me.id)
            except TelegramAPIError as exc:
                errors.append(f"库存通知群（{chat_id}）无法访问：{exc}")
                continue
            if not can_receive_stock_notice(membership):
                errors.append(
                    f"库存通知群（{chat_id}）中机器人不是成员或无法发送消息。"
                )
                continue
            print(f"[通过] 库存通知群：{chat.title or chat_id}，机器人可访问")
    finally:
        await bot.session.close()

    for error in errors:
        print(f"[失败] {error}")
    if errors:
        print("Telegram 联通性检查未通过。")
        return 1
    print("Telegram Token、频道访问和管理员身份检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
