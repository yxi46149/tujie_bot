from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from app.config import PROJECT_ROOT
from app.database import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从本地文本文件安全导入卡密，不经过 Telegram。"
    )
    parser.add_argument("product_id", type=int, help="商品 ID")
    parser.add_argument("file", type=Path, help="UTF-8 文本文件，每行一条卡密")
    return parser.parse_args()


def get_database_path() -> Path:
    value = os.getenv("DATABASE_PATH", "data/bot.db").strip()
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


async def run() -> None:
    args = parse_args()
    codes = args.file.read_text(encoding="utf-8-sig").splitlines()
    database = Database(get_database_path())
    await database.initialize()
    inserted = await database.add_cards(args.product_id, codes)
    if inserted == -1:
        raise SystemExit(f"商品 ID {args.product_id} 不存在。")
    print(f"成功导入 {inserted} 条新卡密；空行和重复卡密已忽略。")


if __name__ == "__main__":
    asyncio.run(run())
