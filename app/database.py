from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import randbelow, token_urlsafe
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


@dataclass(frozen=True, slots=True)
class LotteryDrawOutcome:
    status: str
    prize_name: str = ""
    prize_type: str = ""
    code: str = ""
    points: int = 0
    cost: int = 0
    points_delta: int = 0


@dataclass(frozen=True, slots=True)
class GroupLotteryCreateOutcome:
    status: str
    lottery_id: int | None = None
    product_name: str = ""
    stock: int = 0
    trigger_text: str = ""
    draw_mode: str = ""
    target_participants: int | None = None
    draw_at: str | None = None


@dataclass(frozen=True, slots=True)
class GroupLotteryJoinOutcome:
    status: str
    title: str = ""
    participant_count: int = 0
    target_participants: int | None = None
    should_draw: bool = False
    previous_feedback_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class GroupLotteryWinner:
    user_id: int
    username: str | None
    first_name: str
    prize_type: str
    prize_name: str
    points_delta: int = 0
    code: str = ""


@dataclass(frozen=True, slots=True)
class GroupLotteryDrawOutcome:
    status: str
    title: str = ""
    prize_type: str = ""
    prize_name: str = ""
    points_delta: int = 0
    participant_count: int = 0
    winner_count: int = 0
    stock: int = 0
    winners: tuple[GroupLotteryWinner, ...] = ()


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

                CREATE TABLE IF NOT EXISTS lottery_prizes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    prize_type TEXT NOT NULL
                        CHECK(prize_type IN ('none', 'points', 'product')),
                    weight INTEGER NOT NULL CHECK(weight > 0),
                    points_delta INTEGER NOT NULL DEFAULT 0,
                    product_id INTEGER,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    CHECK(
                        (prize_type = 'none' AND points_delta = 0 AND product_id IS NULL)
                        OR
                        (prize_type = 'points' AND points_delta > 0 AND product_id IS NULL)
                        OR
                        (prize_type = 'product' AND points_delta = 0 AND product_id IS NOT NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_lottery_prizes_active
                    ON lottery_prizes(is_active, id);

                CREATE TABLE IF NOT EXISTS lottery_draws (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    prize_id INTEGER NOT NULL,
                    prize_name TEXT NOT NULL,
                    prize_type TEXT NOT NULL,
                    cost_points INTEGER NOT NULL,
                    points_delta INTEGER NOT NULL DEFAULT 0,
                    product_id INTEGER,
                    card_id INTEGER UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(prize_id) REFERENCES lottery_prizes(id),
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(card_id) REFERENCES cards(id)
                );

                CREATE INDEX IF NOT EXISTS idx_lottery_draws_user
                    ON lottery_draws(user_id, id DESC);

                CREATE TABLE IF NOT EXISTS group_lotteries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    created_by INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    trigger_text TEXT NOT NULL DEFAULT '',
                    prize_type TEXT NOT NULL
                        CHECK(prize_type IN ('points', 'product')),
                    points_delta INTEGER NOT NULL DEFAULT 0,
                    product_id INTEGER,
                    winner_count INTEGER NOT NULL CHECK(winner_count > 0),
                    draw_mode TEXT NOT NULL DEFAULT 'manual'
                        CHECK(draw_mode IN ('manual', 'time', 'count')),
                    target_participants INTEGER,
                    draw_at TEXT,
                    last_feedback_message_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'drawn', 'cancelled')),
                    created_at TEXT NOT NULL,
                    drawn_at TEXT,
                    FOREIGN KEY(created_by) REFERENCES users(user_id),
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    CHECK(
                        (prize_type = 'points' AND points_delta > 0 AND product_id IS NULL)
                        OR
                        (prize_type = 'product' AND points_delta = 0 AND product_id IS NOT NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_group_lotteries_chat_status
                    ON group_lotteries(chat_id, status, id DESC);

                CREATE TABLE IF NOT EXISTS group_lottery_participants (
                    lottery_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(lottery_id, user_id),
                    FOREIGN KEY(lottery_id) REFERENCES group_lotteries(id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_group_lottery_participants_lottery
                    ON group_lottery_participants(lottery_id, created_at);

                CREATE TABLE IF NOT EXISTS group_lottery_winners (
                    lottery_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    prize_type TEXT NOT NULL,
                    prize_name TEXT NOT NULL,
                    points_delta INTEGER NOT NULL DEFAULT 0,
                    product_id INTEGER,
                    card_id INTEGER UNIQUE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(lottery_id, user_id),
                    FOREIGN KEY(lottery_id) REFERENCES group_lotteries(id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(card_id) REFERENCES cards(id)
                );

                CREATE INDEX IF NOT EXISTS idx_group_lottery_winners_user
                    ON group_lottery_winners(user_id, lottery_id DESC);
                """
            )
            await self._ensure_columns(
                db,
                "group_lotteries",
                {
                    "trigger_text": "TEXT NOT NULL DEFAULT ''",
                    "draw_mode": "TEXT NOT NULL DEFAULT 'manual'",
                    "target_participants": "INTEGER",
                    "draw_at": "TEXT",
                    "last_feedback_message_id": "INTEGER",
                },
            )
            await db.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_group_lotteries_trigger
                    ON group_lotteries(chat_id, status, trigger_text);

                CREATE INDEX IF NOT EXISTS idx_group_lotteries_due
                    ON group_lotteries(status, draw_mode, draw_at);
                """
            )
            await db.commit()

    async def _ensure_columns(
        self, db: aiosqlite.Connection, table: str, columns: dict[str, str]
    ) -> None:
        existing = {
            str(row["name"])
            for row in await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
        }
        for column, definition in columns.items():
            if column not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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

    async def get_points_rank(self, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT user_id, username, first_name, points
                FROM users
                WHERE points > 0
                ORDER BY points DESC, updated_at ASC, user_id ASC
                LIMIT ?
                """,
                (limit,),
            )
            return list(await cursor.fetchall())

    async def list_lottery_prizes(
        self, active_only: bool = True
    ) -> list[aiosqlite.Row]:
        condition = "WHERE lp.is_active = 1" if active_only else ""
        async with self.connection() as db:
            cursor = await db.execute(
                f"""
                SELECT lp.*, p.name AS product_name, p.is_active AS product_is_active,
                       COALESCE(
                           SUM(
                               CASE
                                   WHEN c.id IS NOT NULL AND c.redeemed_by IS NULL
                                   THEN 1 ELSE 0
                               END
                           ),
                           0
                       ) AS stock
                FROM lottery_prizes lp
                LEFT JOIN products p ON p.id = lp.product_id
                LEFT JOIN cards c ON c.product_id = p.id
                {condition}
                GROUP BY lp.id
                ORDER BY lp.id
                """
            )
            return list(await cursor.fetchall())

    async def add_lottery_prize(
        self,
        name: str,
        prize_type: str,
        weight: int,
        points_delta: int = 0,
        product_id: int | None = None,
    ) -> int | None:
        prize_type = prize_type.strip().lower()
        name = name.strip()
        if not name or weight <= 0:
            return None
        if prize_type == "none":
            points_delta = 0
            product_id = None
        elif prize_type == "points":
            if points_delta <= 0:
                return None
            product_id = None
        elif prize_type == "product":
            if product_id is None:
                return None
            points_delta = 0
        else:
            return None

        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            if product_id is not None:
                product = await (
                    await db.execute("SELECT 1 FROM products WHERE id = ?", (product_id,))
                ).fetchone()
                if not product:
                    await db.rollback()
                    return None
            cursor = await db.execute(
                """
                INSERT INTO lottery_prizes(
                    name, prize_type, weight, points_delta, product_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, prize_type, weight, points_delta, product_id, utc_now()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def toggle_lottery_prize(self, prize_id: int) -> bool | None:
        async with self.connection() as db:
            prize = await (
                await db.execute(
                    "SELECT is_active FROM lottery_prizes WHERE id = ?", (prize_id,)
                )
            ).fetchone()
            if not prize:
                return None
            new_value = 0 if prize["is_active"] else 1
            await db.execute(
                "UPDATE lottery_prizes SET is_active = ? WHERE id = ?",
                (new_value, prize_id),
            )
            await db.commit()
            return bool(new_value)

    async def draw_lottery(
        self, user_id: int, cost_points: int
    ) -> LotteryDrawOutcome:
        if cost_points <= 0:
            raise ValueError("抽奖消耗积分必须大于 0。")

        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            user = await (
                await db.execute(
                    "SELECT points FROM users WHERE user_id = ?", (user_id,)
                )
            ).fetchone()
            if not user:
                await db.rollback()
                return LotteryDrawOutcome(status="not_registered", cost=cost_points)

            current_points = int(user["points"])
            if current_points < cost_points:
                await db.rollback()
                return LotteryDrawOutcome(
                    status="insufficient_points",
                    points=current_points,
                    cost=cost_points,
                )

            prizes = list(
                await (
                    await db.execute(
                        """
                        SELECT lp.*
                        FROM lottery_prizes lp
                        WHERE lp.is_active = 1
                          AND (
                              lp.prize_type != 'product'
                              OR EXISTS (
                                  SELECT 1
                                  FROM products p
                                  JOIN cards c ON c.product_id = p.id
                                  WHERE p.id = lp.product_id
                                    AND p.is_active = 1
                                    AND c.redeemed_by IS NULL
                                  LIMIT 1
                              )
                          )
                        ORDER BY lp.id
                        """
                    )
                ).fetchall()
            )
            total_weight = sum(int(prize["weight"]) for prize in prizes)
            if total_weight <= 0:
                await db.rollback()
                return LotteryDrawOutcome(
                    status="no_prizes", points=current_points, cost=cost_points
                )

            ticket = randbelow(total_weight)
            selected = prizes[-1]
            running = 0
            for prize in prizes:
                running += int(prize["weight"])
                if ticket < running:
                    selected = prize
                    break

            prize_type = str(selected["prize_type"])
            prize_name = str(selected["name"])
            points_delta = int(selected["points_delta"])
            product_id = (
                int(selected["product_id"]) if selected["product_id"] is not None else None
            )
            card_id: int | None = None
            code = ""

            if prize_type == "product":
                card = await (
                    await db.execute(
                        """
                        SELECT c.id, c.code
                        FROM cards c
                        JOIN products p ON p.id = c.product_id
                        WHERE c.product_id = ?
                          AND p.is_active = 1
                          AND c.redeemed_by IS NULL
                        ORDER BY c.id
                        LIMIT 1
                        """,
                        (product_id,),
                    )
                ).fetchone()
                if not card:
                    await db.rollback()
                    return LotteryDrawOutcome(
                        status="no_prizes", points=current_points, cost=cost_points
                    )
                card_id = int(card["id"])
                code = str(card["code"])
                await db.execute(
                    """
                    UPDATE cards SET redeemed_by = ?, redeemed_at = ?
                    WHERE id = ? AND redeemed_by IS NULL
                    """,
                    (user_id, now, card_id),
                )

            new_points = current_points - cost_points + points_delta
            await db.execute(
                "UPDATE users SET points = ?, updated_at = ? WHERE user_id = ?",
                (new_points, now, user_id),
            )
            await db.execute(
                """
                INSERT INTO point_transactions(user_id, delta, reason, created_at)
                VALUES (?, ?, 'lottery_cost', ?)
                """,
                (user_id, -cost_points, now),
            )
            if points_delta:
                await db.execute(
                    """
                    INSERT INTO point_transactions(user_id, delta, reason, created_at)
                    VALUES (?, ?, 'lottery_points_prize', ?)
                    """,
                    (user_id, points_delta, now),
                )
            if product_id is not None and card_id is not None:
                await db.execute(
                    """
                    INSERT INTO redemptions(
                        user_id, product_id, card_id, points_spent, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, product_id, card_id, cost_points, now),
                )
            await db.execute(
                """
                INSERT INTO lottery_draws(
                    user_id, prize_id, prize_name, prize_type, cost_points,
                    points_delta, product_id, card_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    int(selected["id"]),
                    prize_name,
                    prize_type,
                    cost_points,
                    points_delta,
                    product_id,
                    card_id,
                    now,
                ),
            )
            await db.commit()
            return LotteryDrawOutcome(
                status="ok",
                prize_name=prize_name,
                prize_type=prize_type,
                code=code,
                points=new_points,
                cost=cost_points,
                points_delta=points_delta,
            )

    async def create_group_lottery(
        self,
        chat_id: int,
        created_by: int,
        title: str,
        prize_type: str,
        prize_value: int,
        winner_count: int,
        trigger_text: str = "",
        draw_mode: str = "manual",
        target_participants: int | None = None,
        draw_at: str | None = None,
    ) -> GroupLotteryCreateOutcome:
        title = title.strip()
        prize_type = prize_type.strip().lower()
        trigger_text = trigger_text.strip()
        draw_mode = draw_mode.strip().lower()
        if not title or prize_value <= 0 or winner_count <= 0:
            return GroupLotteryCreateOutcome(status="invalid")
        if draw_mode not in {"manual", "time", "count"}:
            return GroupLotteryCreateOutcome(status="invalid")
        if draw_mode in {"time", "count"} and not trigger_text:
            return GroupLotteryCreateOutcome(status="invalid")
        if draw_mode == "time" and not draw_at:
            return GroupLotteryCreateOutcome(status="invalid")
        if draw_mode == "count" and (
            target_participants is None or target_participants < winner_count
        ):
            return GroupLotteryCreateOutcome(status="invalid")
        if draw_mode != "count":
            target_participants = None
        if draw_mode != "time":
            draw_at = None

        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            creator = await (
                await db.execute("SELECT 1 FROM users WHERE user_id = ?", (created_by,))
            ).fetchone()
            if not creator:
                await db.rollback()
                return GroupLotteryCreateOutcome(status="creator_not_registered")
            if trigger_text:
                duplicate_trigger = await (
                    await db.execute(
                        """
                        SELECT 1 FROM group_lotteries
                        WHERE chat_id = ? AND status = 'pending'
                          AND trigger_text = ?
                        LIMIT 1
                        """,
                        (chat_id, trigger_text),
                    )
                ).fetchone()
                if duplicate_trigger:
                    await db.rollback()
                    return GroupLotteryCreateOutcome(status="duplicate_trigger")

            points_delta = 0
            product_id: int | None = None
            product_name = ""
            stock = 0
            if prize_type == "points":
                points_delta = prize_value
            elif prize_type == "product":
                product_id = prize_value
                product = await (
                    await db.execute(
                        """
                        SELECT p.name, p.is_active,
                               COALESCE(
                                   SUM(
                                       CASE
                                           WHEN c.id IS NOT NULL
                                            AND c.redeemed_by IS NULL
                                           THEN 1 ELSE 0
                                       END
                                   ),
                                   0
                               ) AS stock
                        FROM products p
                        LEFT JOIN cards c ON c.product_id = p.id
                        WHERE p.id = ?
                        GROUP BY p.id
                        """,
                        (product_id,),
                    )
                ).fetchone()
                if not product:
                    await db.rollback()
                    return GroupLotteryCreateOutcome(status="product_not_found")
                if not product["is_active"]:
                    await db.rollback()
                    return GroupLotteryCreateOutcome(
                        status="product_inactive",
                        product_name=str(product["name"]),
                    )
                product_name = str(product["name"])
                stock = int(product["stock"] or 0)
                if stock < winner_count:
                    await db.rollback()
                    return GroupLotteryCreateOutcome(
                        status="insufficient_stock",
                        product_name=product_name,
                        stock=stock,
                    )
            else:
                await db.rollback()
                return GroupLotteryCreateOutcome(status="invalid")

            cursor = await db.execute(
                """
                INSERT INTO group_lotteries(
                    chat_id, created_by, title, trigger_text, prize_type,
                    points_delta, product_id, winner_count, draw_mode,
                    target_participants, draw_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    created_by,
                    title,
                    trigger_text,
                    prize_type,
                    points_delta,
                    product_id,
                    winner_count,
                    draw_mode,
                    target_participants,
                    draw_at,
                    now,
                ),
            )
            await db.commit()
            return GroupLotteryCreateOutcome(
                status="ok",
                lottery_id=int(cursor.lastrowid),
                product_name=product_name,
                stock=stock,
                trigger_text=trigger_text,
                draw_mode=draw_mode,
                target_participants=target_participants,
                draw_at=draw_at,
            )

    async def set_group_lottery_message(
        self, lottery_id: int, message_id: int
    ) -> None:
        async with self.connection() as db:
            await db.execute(
                "UPDATE group_lotteries SET message_id = ? WHERE id = ?",
                (message_id, lottery_id),
            )
            await db.commit()

    async def get_group_lottery(self, lottery_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute(
                    """
                    SELECT gl.*, p.name AS product_name,
                           COALESCE(
                               SUM(
                                   CASE
                                       WHEN c.id IS NOT NULL AND c.redeemed_by IS NULL
                                       THEN 1 ELSE 0
                                   END
                               ),
                               0
                           ) AS stock,
                           (
                               SELECT COUNT(*)
                               FROM group_lottery_participants glp
                               WHERE glp.lottery_id = gl.id
                           ) AS participant_count
                    FROM group_lotteries gl
                    LEFT JOIN products p ON p.id = gl.product_id
                    LEFT JOIN cards c ON c.product_id = p.id
                    WHERE gl.id = ?
                    GROUP BY gl.id
                    """,
                    (lottery_id,),
                )
            ).fetchone()

    async def get_group_lottery_by_trigger(
        self, chat_id: int, trigger_text: str
    ) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute(
                    """
                    SELECT *
                    FROM group_lotteries
                    WHERE chat_id = ? AND status = 'pending'
                      AND trigger_text = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (chat_id, trigger_text.strip()),
                )
            ).fetchone()

    async def list_due_group_lotteries(self, now: str) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM group_lotteries
                WHERE status = 'pending'
                  AND draw_mode = 'time'
                  AND draw_at IS NOT NULL
                  AND draw_at <= ?
                ORDER BY draw_at, id
                """,
                (now,),
            )
            return list(await cursor.fetchall())

    async def set_group_lottery_feedback(
        self, lottery_id: int, message_id: int
    ) -> None:
        async with self.connection() as db:
            await db.execute(
                """
                UPDATE group_lotteries
                SET last_feedback_message_id = ?
                WHERE id = ? AND status = 'pending'
                """,
                (message_id, lottery_id),
            )
            await db.commit()

    async def cancel_group_lottery(self, lottery_id: int) -> bool:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                UPDATE group_lotteries
                SET status = 'cancelled', drawn_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (utc_now(), lottery_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def join_group_lottery(
        self,
        lottery_id: int,
        user_id: int,
        username: str | None,
        first_name: str,
    ) -> GroupLotteryJoinOutcome:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            lottery = await (
                await db.execute(
                    """
                    SELECT title, status, draw_mode, target_participants,
                           last_feedback_message_id
                    FROM group_lotteries WHERE id = ?
                    """,
                    (lottery_id,),
                )
            ).fetchone()
            if not lottery:
                await db.rollback()
                return GroupLotteryJoinOutcome(status="not_found")
            if lottery["status"] != "pending":
                await db.rollback()
                return GroupLotteryJoinOutcome(
                    status=str(lottery["status"]),
                    title=str(lottery["title"]),
                )
            target_participants = (
                int(lottery["target_participants"])
                if lottery["target_participants"] is not None
                else None
            )
            previous_feedback_message_id = (
                int(lottery["last_feedback_message_id"])
                if lottery["last_feedback_message_id"] is not None
                else None
            )
            snapshot = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS count,
                           SUM(CASE WHEN user_id = ? THEN 1 ELSE 0 END) AS joined
                    FROM group_lottery_participants
                    WHERE lottery_id = ?
                    """,
                    (user_id, lottery_id),
                )
            ).fetchone()
            existing_count = int(snapshot["count"] or 0)
            if int(snapshot["joined"] or 0) > 0:
                await db.execute(
                    """
                    UPDATE group_lottery_participants
                    SET username = ?, first_name = ?
                    WHERE lottery_id = ? AND user_id = ?
                    """,
                    (username, first_name, lottery_id, user_id),
                )
                await db.commit()
                return GroupLotteryJoinOutcome(
                    status="already_joined",
                    title=str(lottery["title"]),
                    participant_count=existing_count,
                    target_participants=target_participants,
                )
            if (
                lottery["draw_mode"] == "count"
                and target_participants is not None
                and existing_count >= target_participants
            ):
                await db.rollback()
                return GroupLotteryJoinOutcome(
                    status="filled",
                    title=str(lottery["title"]),
                    participant_count=existing_count,
                    target_participants=target_participants,
                )
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO group_lottery_participants(
                    lottery_id, user_id, username, first_name, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (lottery_id, user_id, username, first_name, now),
            )
            count_row = await (
                await db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM group_lottery_participants
                    WHERE lottery_id = ?
                    """,
                    (lottery_id,),
                )
            ).fetchone()
            participant_count = int(count_row["count"] or 0)
            await db.commit()
            if cursor.rowcount != 1:
                return GroupLotteryJoinOutcome(
                    status="already_joined",
                    title=str(lottery["title"]),
                    participant_count=participant_count,
                    target_participants=target_participants,
                )
            return GroupLotteryJoinOutcome(
                status="ok",
                title=str(lottery["title"]),
                participant_count=participant_count,
                target_participants=target_participants,
                should_draw=bool(
                    lottery["draw_mode"] == "count"
                    and target_participants is not None
                    and participant_count >= target_participants
                ),
                previous_feedback_message_id=previous_feedback_message_id,
            )

    async def draw_group_lottery(
        self, lottery_id: int
    ) -> GroupLotteryDrawOutcome:
        now = utc_now()
        async with self.connection() as db:
            await db.execute("BEGIN IMMEDIATE")
            lottery = await (
                await db.execute(
                    """
                    SELECT gl.*, p.name AS product_name, p.is_active AS product_is_active
                    FROM group_lotteries gl
                    LEFT JOIN products p ON p.id = gl.product_id
                    WHERE gl.id = ?
                    """,
                    (lottery_id,),
                )
            ).fetchone()
            if not lottery:
                await db.rollback()
                return GroupLotteryDrawOutcome(status="not_found")
            if lottery["status"] != "pending":
                await db.rollback()
                return GroupLotteryDrawOutcome(
                    status=str(lottery["status"]),
                    title=str(lottery["title"]),
                )

            participants = list(
                await (
                    await db.execute(
                        """
                        SELECT user_id, username, first_name
                        FROM group_lottery_participants
                        WHERE lottery_id = ?
                        ORDER BY created_at, user_id
                        """,
                        (lottery_id,),
                    )
                ).fetchall()
            )
            participant_count = len(participants)
            if participant_count == 0:
                await db.rollback()
                return GroupLotteryDrawOutcome(
                    status="no_participants",
                    title=str(lottery["title"]),
                    participant_count=0,
                )

            winner_count = min(int(lottery["winner_count"]), participant_count)
            prize_type = str(lottery["prize_type"])
            prize_name = (
                str(lottery["product_name"])
                if prize_type == "product"
                else f"{int(lottery['points_delta'])} 积分"
            )
            points_delta = int(lottery["points_delta"])
            product_id = (
                int(lottery["product_id"]) if lottery["product_id"] is not None else None
            )

            if prize_type == "product":
                if not lottery["product_is_active"]:
                    await db.rollback()
                    return GroupLotteryDrawOutcome(
                        status="product_inactive",
                        title=str(lottery["title"]),
                        prize_type=prize_type,
                        prize_name=prize_name,
                        participant_count=participant_count,
                        winner_count=winner_count,
                    )
                stock_row = await (
                    await db.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM cards
                        WHERE product_id = ? AND redeemed_by IS NULL
                        """,
                        (product_id,),
                    )
                ).fetchone()
                stock = int(stock_row["count"] or 0)
                if stock < winner_count:
                    await db.rollback()
                    return GroupLotteryDrawOutcome(
                        status="insufficient_stock",
                        title=str(lottery["title"]),
                        prize_type=prize_type,
                        prize_name=prize_name,
                        participant_count=participant_count,
                        winner_count=winner_count,
                        stock=stock,
                    )

            remaining = participants[:]
            winners: list[aiosqlite.Row] = []
            for _ in range(winner_count):
                index = randbelow(len(remaining))
                winners.append(remaining.pop(index))

            winner_results: list[GroupLotteryWinner] = []
            for winner in winners:
                user_id = int(winner["user_id"])
                code = ""
                card_id: int | None = None
                if prize_type == "points":
                    await db.execute(
                        """
                        UPDATE users
                        SET points = points + ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (points_delta, now, user_id),
                    )
                    await db.execute(
                        """
                        INSERT INTO point_transactions(
                            user_id, delta, reason, created_at
                        ) VALUES (?, ?, 'group_lottery_points_prize', ?)
                        """,
                        (user_id, points_delta, now),
                    )
                else:
                    card = await (
                        await db.execute(
                            """
                            SELECT id, code
                            FROM cards
                            WHERE product_id = ? AND redeemed_by IS NULL
                            ORDER BY id
                            LIMIT 1
                            """,
                            (product_id,),
                        )
                    ).fetchone()
                    if not card:
                        await db.rollback()
                        return GroupLotteryDrawOutcome(
                            status="insufficient_stock",
                            title=str(lottery["title"]),
                            prize_type=prize_type,
                            prize_name=prize_name,
                            participant_count=participant_count,
                            winner_count=winner_count,
                        )
                    card_id = int(card["id"])
                    code = str(card["code"])
                    await db.execute(
                        """
                        UPDATE cards SET redeemed_by = ?, redeemed_at = ?
                        WHERE id = ? AND redeemed_by IS NULL
                        """,
                        (user_id, now, card_id),
                    )
                    await db.execute(
                        """
                        INSERT INTO redemptions(
                            user_id, product_id, card_id, points_spent, created_at
                        ) VALUES (?, ?, ?, 0, ?)
                        """,
                        (user_id, product_id, card_id, now),
                    )

                await db.execute(
                    """
                    INSERT INTO group_lottery_winners(
                        lottery_id, user_id, prize_type, prize_name,
                        points_delta, product_id, card_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lottery_id,
                        user_id,
                        prize_type,
                        prize_name,
                        points_delta,
                        product_id,
                        card_id,
                        now,
                    ),
                )
                winner_results.append(
                    GroupLotteryWinner(
                        user_id=user_id,
                        username=winner["username"],
                        first_name=str(winner["first_name"] or "用户"),
                        prize_type=prize_type,
                        prize_name=prize_name,
                        points_delta=points_delta,
                        code=code,
                    )
                )

            await db.execute(
                """
                UPDATE group_lotteries
                SET status = 'drawn', drawn_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, lottery_id),
            )
            await db.commit()
            return GroupLotteryDrawOutcome(
                status="ok",
                title=str(lottery["title"]),
                prize_type=prize_type,
                prize_name=prize_name,
                points_delta=points_delta,
                participant_count=participant_count,
                winner_count=winner_count,
                winners=tuple(winner_results),
            )

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
            "active_lottery_prizes": (
                "SELECT COUNT(*) FROM lottery_prizes WHERE is_active = 1"
            ),
            "lottery_draws": "SELECT COUNT(*) FROM lottery_draws",
            "group_lotteries": "SELECT COUNT(*) FROM group_lotteries",
            "drawn_group_lotteries": (
                "SELECT COUNT(*) FROM group_lotteries WHERE status = 'drawn'"
            ),
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
