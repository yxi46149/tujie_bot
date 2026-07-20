from __future__ import annotations

from html import escape


def mask_name(value: str) -> str:
    value = value.strip()
    if not value:
        return "用户"
    if len(value) == 1:
        return "*"
    if len(value) == 2:
        return f"{value[0]}*"
    if len(value) == 3:
        return f"{value[0]}*{value[-1]}"
    if len(value) == 4:
        return f"{value[0]}***{value[-1]}"
    return f"{value[:2]}***{value[-2:]}"


def masked_public_name(username: object, first_name: object) -> str:
    if username:
        return f"@{mask_name(str(username))}"
    return mask_name(str(first_name or "用户"))


def masked_user_link(user_id: int, username: object, first_name: object) -> str:
    display = masked_public_name(username, first_name)
    return f'<a href="tg://user?id={user_id}">{escape(display)}</a>'
