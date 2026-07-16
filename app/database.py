from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_urlsafe
from typing import AsyncIterator, Iterable

import aiosqlite


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    settled: bool = False
    rewarded: bool = False
    inviter_id: int | None = None
    reward_points: int = 0
    limited: bool = False


@dataclass(frozen=True, slots=True)
class CheckinOutcome:
    claimed: bool
    points: int


@dataclass(frozen=True, slots=True)
class RedeemOutcome:
    status: str
    product_name: str = ""
    code: str = ""
    points: int = 0
    cost: int = 0


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        try:
            yield db
        finally:
            await db.close()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connection() as db:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL DEFAULT '',
                    points INTEGER NOT NULL DEFAULT 0 CHECK(points >= 0),
                    is_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS referrals (
                    invitee_id INTEGER PRIMARY KEY,
                    inviter_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'verified')),
                    reward_points INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    verified_at TEXT,
                    FOREIGN KEY(invitee_id) REFERENCES users(user_id),
                    FOREIGN KEY(inviter_id) REFERENCES users(user_id),
                    CHECK(invitee_id <> inviter_id)
                );

                CREATE INDEX IF NOT EXISTS idx_referrals_inviter_status
                    ON referrals(inviter_id, status);

                CREATE TABLE IF NOT EXISTS point_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    delta INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    related_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_point_transactions_user
                    ON point_transactions(user_id, id DESC);

                CREATE TABLE IF NOT EXISTS checkins (
                    user_id INTEGER NOT NULL,
                    checkin_date TEXT NOT NULL,
                    reward_points INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, checkin_date),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    points_cost INTEGER NOT NULL CHECK(points_cost > 0),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    code TEXT NOT NULL UNIQUE,
                    redeemed_by INTEGER,
                    redeemed_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(redeemed_by) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_cards_product_available
                    ON cards(product_id, redeemed_by);

                CREATE TABLE IF NOT EXISTS redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    card_id INTEGER NOT NULL UNIQUE,
                    points_spent INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(card_id) REFERENCES cards(id)
                );

                CREATE INDEX IF NOT EXISTS idx_redemptions_user
                    ON redemptions(user_id, id DESC);

                CREATE TABLE IF NOT EXISTS redemption_intents (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'completed', 'expired')),
                    expires_at TEXT NOT NULL,
                    redemption_id INTEGER UNIQUE,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(redemption_id) REFERENCES redemptions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_redemption_intents_user_status
                    ON redemption_intents(user_id, status, created_at DESC);
                """
            )
            await db.commit()

    async def register_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str,
        inviter_id: int | None = None,
    ) -> bool:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO users(
                    user_id, username, first_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, first_name, now, now),
            )
            created = cursor.rowcount == 1
            await db.execute(
                """
                UPDATE users
                SET username = ?, first_name = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (username, first_name, now, user_id),
            )

            if created and inviter_id and inviter_id != user_id:
                inviter = await (
                    await db.execute(
                        "SELECT 1 FROM users WHERE user_id = ?", (inviter_id,)
                    )
                ).fetchone()
                if inviter:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO referrals(
                            invitee_id, inviter_id, created_at
                        ) VALUES (?, ?, ?)
                        """,
                        (user_id, inviter_id, now),
                    )
            await db.commit()
            return created

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            ).fetchone()

    async def get_invite_counts(self, user_id: int) -> tuple[int, int]:
        async with self.connection() as db:
            row = await (
                await db.execute(
                    """
                    SELECT
                        SUM(CASE WHEN status = 'verified' THEN 1 ELSE 0 END) AS verified,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
                    FROM referrals WHERE inviter_id = ?
                    """,
                    (user_id,),
                )
            ).fetchone()
            return int(row["verified"] or 0), int(row["pending"] or 0)

    async def get_recent_invites(
        self, user_id: int, limit: int = 20
    ) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT r.invitee_id, r.status, r.created_at, r.verified_at,
                       u.username, u.first_name
                FROM referrals r
                JOIN users u ON u.user_id = r.invitee_id
                WHERE r.inviter_id = ?
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            return list(await cursor.fetchall())

    async def verify_and_reward(
        self,
        user_id: int,
        reward_points: int,
        daily_limit: int = 0,
        day_start_utc: str = "",
        day_end_utc: str = "",
    ) -> VerificationOutcome:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE users SET is_verified = 1, updated_at = ? WHERE user_id = ?",
                (now, user_id),
            )
            referral = await (
                await db.execute(
                    """
                    SELECT inviter_id FROM referrals
                    WHERE invitee_id = ? AND status = 'pending'
                    """,
                    (user_id,),
                )
            ).fetchone()
            if not referral:
                await db.commit()
                return VerificationOutcome()

            inviter_id = int(referral["inviter_id"])
            effective_reward = reward_points
            limited = False
            if daily_limit > 0 and day_start_utc and day_end_utc:
                rewarded_today = await (
                    await db.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM referrals
                        WHERE inviter_id = ?
                          AND status = 'verified'
                          AND reward_points > 0
                          AND verified_at >= ?
                          AND verified_at < ?
                        """,
                        (inviter_id, day_start_utc, day_end_utc),
                    )
                ).fetchone()
                if int(rewarded_today["count"]) >= daily_limit:
                    effective_reward = 0
                    limited = True
            cursor = await db.execute(
                """
                UPDATE referrals
                SET status = 'verified', reward_points = ?, verified_at = ?
                WHERE invitee_id = ? AND status = 'pending'
                """,
                (effective_reward, now, user_id),
            )
            if cursor.rowcount != 1:
                await db.commit()
                return VerificationOutcome()

            if effective_reward:
                await db.execute(
                    "UPDATE users SET points = points + ?, updated_at = ? WHERE user_id = ?",
                    (effective_reward, now, inviter_id),
                )
                await db.execute(
                    """
                    INSERT INTO point_transactions(
                        user_id, delta, reason, related_user_id, created_at
                    ) VALUES (?, ?, 'invite_reward', ?, ?)
                    """,
                    (inviter_id, effective_reward, user_id, now),
                )
            await db.commit()
            return VerificationOutcome(
                settled=True,
                rewarded=effective_reward > 0,
                inviter_id=inviter_id,
                reward_points=effective_reward,
                limited=limited,
            )

    async def claim_checkin(
        self, user_id: int, checkin_date: str, reward_points: int
    ) -> CheckinOutcome:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO checkins(
                    user_id, checkin_date, reward_points, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (user_id, checkin_date, reward_points, now),
            )
            claimed = cursor.rowcount == 1
            if claimed and reward_points:
                await db.execute(
                    "UPDATE users SET points = points + ?, updated_at = ? WHERE user_id = ?",
                    (reward_points, now, user_id),
                )
                await db.execute(
                    """
                    INSERT INTO point_transactions(user_id, delta, reason, created_at)
                    VALUES (?, ?, 'daily_checkin', ?)
                    """,
                    (user_id, reward_points, now),
                )
            row = await (
                await db.execute(
                    "SELECT points FROM users WHERE user_id = ?", (user_id,)
                )
            ).fetchone()
            await db.commit()
            return CheckinOutcome(claimed=claimed, points=int(row["points"]))

    async def get_rank(self, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT u.user_id, u.username, u.first_name, COUNT(*) AS invite_count
                FROM referrals r
                JOIN users u ON u.user_id = r.inviter_id
                WHERE r.status = 'verified'
                GROUP BY r.inviter_id
                ORDER BY invite_count DESC, MIN(r.verified_at) ASC
                LIMIT ?
                """,
                (limit,),
            )
            return list(await cursor.fetchall())

    async def list_products(self, active_only: bool = True) -> list[aiosqlite.Row]:
        condition = "WHERE p.is_active = 1" if active_only else ""
        async with self.connection() as db:
            cursor = await db.execute(
                f"""
                SELECT p.*,
                       SUM(CASE WHEN c.id IS NOT NULL AND c.redeemed_by IS NULL
                                THEN 1 ELSE 0 END) AS stock,
                       COUNT(c.id) AS total_cards
                FROM products p
                LEFT JOIN cards c ON c.product_id = p.id
                {condition}
                GROUP BY p.id
                ORDER BY p.id
                """
            )
            return list(await cursor.fetchall())

    async def get_product(self, product_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute(
                    """
                    SELECT p.*,
                           SUM(CASE WHEN c.id IS NOT NULL AND c.redeemed_by IS NULL
                                    THEN 1 ELSE 0 END) AS stock
                    FROM products p
                    LEFT JOIN cards c ON c.product_id = p.id
                    WHERE p.id = ?
                    GROUP BY p.id
                    """,
                    (product_id,),
                )
            ).fetchone()

    async def create_redemption_intent(
        self, user_id: int, product_id: int, ttl_seconds: int
    ) -> str:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds")
        expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat(
            timespec="seconds"
        )
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                UPDATE redemption_intents
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (now,),
            )
            existing = await (
                await db.execute(
                    """
                    SELECT token FROM redemption_intents
                    WHERE user_id = ? AND product_id = ?
                      AND status = 'pending' AND expires_at > ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (user_id, product_id, now),
                )
            ).fetchone()
            if existing:
                await db.commit()
                return str(existing["token"])
            for _ in range(3):
                token = token_urlsafe(16)
                try:
                    await db.execute(
                        """
                        INSERT INTO redemption_intents(
                            token, user_id, product_id, expires_at, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (token, user_id, product_id, expires_at, now),
                    )
                except aiosqlite.IntegrityError:
                    continue
                await db.commit()
                return token
        raise RuntimeError("无法生成唯一兑换意图，请稍后重试。")

    async def redeem_card(self, user_id: int, intent_token: str) -> RedeemOutcome:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            intent = await (
                await db.execute(
                    """
                    SELECT ri.*, r.points_spent, c.code, p.name AS product_name,
                           u.points AS current_points
                    FROM redemption_intents ri
                    JOIN users u ON u.user_id = ri.user_id
                    JOIN products p ON p.id = ri.product_id
                    LEFT JOIN redemptions r ON r.id = ri.redemption_id
                    LEFT JOIN cards c ON c.id = r.card_id
                    WHERE ri.token = ? AND ri.user_id = ?
                    """,
                    (intent_token, user_id),
                )
            ).fetchone()
            if not intent:
                await db.rollback()
                return RedeemOutcome(status="invalid_intent")
            if intent["status"] == "completed":
                await db.rollback()
                return RedeemOutcome(
                    status="already_redeemed",
                    product_name=str(intent["product_name"]),
                    code=str(intent["code"]),
                    points=int(intent["current_points"]),
                    cost=int(intent["points_spent"]),
                )
            if intent["status"] != "pending" or str(intent["expires_at"]) <= now:
                await db.execute(
                    """
                    UPDATE redemption_intents
                    SET status = 'expired'
                    WHERE token = ? AND status = 'pending'
                    """,
                    (intent_token,),
                )
                await db.commit()
                return RedeemOutcome(status="expired_intent")

            product_id = int(intent["product_id"])
            product = await (
                await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            ).fetchone()
            if not product or not product["is_active"]:
                await db.rollback()
                return RedeemOutcome(status="not_found")

            user = await (
                await db.execute(
                    "SELECT points FROM users WHERE user_id = ?", (user_id,)
                )
            ).fetchone()
            cost = int(product["points_cost"])
            if not user or int(user["points"]) < cost:
                await db.rollback()
                return RedeemOutcome(
                    status="insufficient_points",
                    product_name=str(product["name"]),
                    points=int(user["points"]) if user else 0,
                    cost=cost,
                )

            card = await (
                await db.execute(
                    """
                    SELECT id, code FROM cards
                    WHERE product_id = ? AND redeemed_by IS NULL
                    ORDER BY id LIMIT 1
                    """,
                    (product_id,),
                )
            ).fetchone()
            if not card:
                await db.rollback()
                return RedeemOutcome(
                    status="out_of_stock",
                    product_name=str(product["name"]),
                    points=int(user["points"]),
                    cost=cost,
                )

            await db.execute(
                """
                UPDATE cards SET redeemed_by = ?, redeemed_at = ?
                WHERE id = ? AND redeemed_by IS NULL
                """,
                (user_id, now, int(card["id"])),
            )
            await db.execute(
                "UPDATE users SET points = points - ?, updated_at = ? WHERE user_id = ?",
                (cost, now, user_id),
            )
            await db.execute(
                """
                INSERT INTO point_transactions(user_id, delta, reason, created_at)
                VALUES (?, ?, 'card_redemption', ?)
                """,
                (user_id, -cost, now),
            )
            redemption_cursor = await db.execute(
                """
                INSERT INTO redemptions(
                    user_id, product_id, card_id, points_spent, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, product_id, int(card["id"]), cost, now),
            )
            await db.execute(
                """
                UPDATE redemption_intents
                SET status = 'completed', redemption_id = ?, consumed_at = ?
                WHERE token = ? AND status = 'pending'
                """,
                (int(redemption_cursor.lastrowid), now, intent_token),
            )
            await db.commit()
            return RedeemOutcome(
                status="ok",
                product_name=str(product["name"]),
                code=str(card["code"]),
                points=int(user["points"]) - cost,
                cost=cost,
            )

    async def get_user_redemptions(
        self, user_id: int, limit: int = 10
    ) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT p.name AS product_name, c.code, r.points_spent, r.created_at
                FROM redemptions r
                JOIN products p ON p.id = r.product_id
                JOIN cards c ON c.id = r.card_id
                WHERE r.user_id = ?
                ORDER BY r.id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            return list(await cursor.fetchall())

    async def add_product(
        self, name: str, points_cost: int, description: str = ""
    ) -> int:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO products(name, description, points_cost, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, description, points_cost, utc_now()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def add_cards(self, product_id: int, codes: Iterable[str]) -> int:
        now = utc_now()
        inserted = 0
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            product = await (
                await db.execute("SELECT 1 FROM products WHERE id = ?", (product_id,))
            ).fetchone()
            if not product:
                await db.rollback()
                return -1
            for raw_code in codes:
                code = raw_code.strip()
                if not code:
                    continue
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO cards(product_id, code, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (product_id, code, now),
                )
                inserted += max(cursor.rowcount, 0)
            await db.commit()
        return inserted

    async def toggle_product(self, product_id: int) -> bool | None:
        async with self.connection() as db:
            product = await (
                await db.execute(
                    "SELECT is_active FROM products WHERE id = ?", (product_id,)
                )
            ).fetchone()
            if not product:
                return None
            new_value = 0 if product["is_active"] else 1
            await db.execute(
                "UPDATE products SET is_active = ? WHERE id = ?",
                (new_value, product_id),
            )
            await db.commit()
            return bool(new_value)

    async def adjust_points(
        self, user_id: int, delta: int, reason: str = "admin_adjustment"
    ) -> int | None:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            user = await (
                await db.execute(
                    "SELECT points FROM users WHERE user_id = ?", (user_id,)
                )
            ).fetchone()
            if not user or int(user["points"]) + delta < 0:
                await db.rollback()
                return None
            await db.execute(
                "UPDATE users SET points = points + ?, updated_at = ? WHERE user_id = ?",
                (delta, now, user_id),
            )
            await db.execute(
                """
                INSERT INTO point_transactions(user_id, delta, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, delta, reason, now),
            )
            await db.commit()
            return int(user["points"]) + delta

    async def get_stats(self) -> dict[str, int]:
        queries = {
            "users": "SELECT COUNT(*) FROM users",
            "verified_users": "SELECT COUNT(*) FROM users WHERE is_verified = 1",
            "verified_referrals": (
                "SELECT COUNT(*) FROM referrals WHERE status = 'verified'"
            ),
            "available_cards": "SELECT COUNT(*) FROM cards WHERE redeemed_by IS NULL",
            "redemptions": "SELECT COUNT(*) FROM redemptions",
        }
        result: dict[str, int] = {}
        async with self.connection() as db:
            for key, query in queries.items():
                row = await (await db.execute(query)).fetchone()
                result[key] = int(row[0])
        return result

    async def quick_check(self) -> str:
        async with self.connection() as db:
            row = await (await db.execute("PRAGMA quick_check")).fetchone()
            return str(row[0]) if row else "no result"
