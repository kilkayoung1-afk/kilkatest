"""Async SQLite storage for users, subscriptions, bots and payments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    tg_id INTEGER PRIMARY KEY REFERENCES users(tg_id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    bot_quota INTEGER NOT NULL,
    total_paid_stars INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_expires_at ON subscriptions(expires_at);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL,
    paid_stars INTEGER NOT NULL,
    days INTEGER NOT NULL,
    bots INTEGER NOT NULL,
    payment_charge_id TEXT,
    paid_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_tg_id ON payments(tg_id);

CREATE TABLE IF NOT EXISTS bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    container_id TEXT,
    container_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    started_at TEXT,
    stopped_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(tg_id, name)
);
CREATE INDEX IF NOT EXISTS idx_bots_tg_id ON bots(tg_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw)


@dataclass(slots=True)
class Subscription:
    tg_id: int
    expires_at: datetime
    bot_quota: int
    total_paid_stars: int

    def is_active(self, *, at: datetime | None = None) -> bool:
        return self.expires_at > (at or datetime.now(UTC))


@dataclass(slots=True)
class BotRecord:
    id: int
    tg_id: int
    name: str
    file_path: str
    container_id: str | None
    container_name: str
    status: str
    started_at: datetime | None
    stopped_at: datetime | None
    last_error: str | None
    created_at: datetime


class Database:
    """Thin async wrapper over a single SQLite file."""

    def __init__(self, path: Path):
        self._path = path

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    # ---- users ----

    async def upsert_user(self, tg_id: int, username: str | None) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO users (tg_id, username, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET username = excluded.username
                """,
                (tg_id, username, _now()),
            )
            await db.commit()

    async def count_users(self) -> int:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute("SELECT COUNT(*) FROM users") as cursor,
        ):
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    # ---- subscriptions ----

    async def get_subscription(self, tg_id: int) -> Subscription | None:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                "SELECT tg_id, expires_at, bot_quota, total_paid_stars FROM subscriptions WHERE tg_id = ?",
                (tg_id,),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        if not row:
            return None
        expires = _parse_dt(row[1])
        assert expires is not None
        return Subscription(
            tg_id=int(row[0]),
            expires_at=expires,
            bot_quota=int(row[2]),
            total_paid_stars=int(row[3]),
        )

    async def apply_payment(
        self,
        *,
        tg_id: int,
        plan_id: str,
        paid_stars: int,
        days: int,
        bots: int,
        payment_charge_id: str | None,
    ) -> Subscription:
        """Apply a new payment to the user's subscription.

        Rules: expires_at = max(current, now) + days; bot_quota = max(current, plan.bots).
        """

        now = datetime.now(UTC)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("BEGIN")
            try:
                async with db.execute(
                    "SELECT expires_at, bot_quota, total_paid_stars FROM subscriptions WHERE tg_id = ?",
                    (tg_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    current_expiry = _parse_dt(row[0]) or now
                    base = current_expiry if current_expiry > now else now
                    new_expiry = base + timedelta(days=days)
                    new_quota = max(int(row[1]), bots)
                    new_total = int(row[2]) + paid_stars
                    await db.execute(
                        """
                        UPDATE subscriptions
                        SET expires_at = ?, bot_quota = ?, total_paid_stars = ?, updated_at = ?
                        WHERE tg_id = ?
                        """,
                        (new_expiry.isoformat(), new_quota, new_total, _now(), tg_id),
                    )
                else:
                    new_expiry = now + timedelta(days=days)
                    new_quota = bots
                    new_total = paid_stars
                    await db.execute(
                        """
                        INSERT INTO subscriptions (tg_id, expires_at, bot_quota, total_paid_stars, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (tg_id, new_expiry.isoformat(), new_quota, new_total, _now()),
                    )
                await db.execute(
                    """
                    INSERT INTO payments (tg_id, plan_id, paid_stars, days, bots, payment_charge_id, paid_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (tg_id, plan_id, paid_stars, days, bots, payment_charge_id, _now()),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return Subscription(
            tg_id=tg_id,
            expires_at=new_expiry,
            bot_quota=new_quota,
            total_paid_stars=new_total,
        )

    async def list_active_subscriptions(self) -> list[Subscription]:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                """
            SELECT tg_id, expires_at, bot_quota, total_paid_stars
            FROM subscriptions
            WHERE expires_at > ?
            ORDER BY expires_at ASC
            """,
                (_now(),),
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        result: list[Subscription] = []
        for row in rows:
            expires = _parse_dt(row[1])
            assert expires is not None
            result.append(
                Subscription(
                    tg_id=int(row[0]),
                    expires_at=expires,
                    bot_quota=int(row[2]),
                    total_paid_stars=int(row[3]),
                )
            )
        return result

    async def total_paid_stars(self) -> int:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute("SELECT COALESCE(SUM(paid_stars), 0) FROM payments") as cur,
        ):
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---- bots ----

    async def create_bot(
        self,
        *,
        tg_id: int,
        name: str,
        file_path: str,
        container_name: str,
    ) -> BotRecord:
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """
                INSERT INTO bots (tg_id, name, file_path, container_name, status, created_at)
                VALUES (?, ?, ?, ?, 'stopped', ?)
                """,
                (tg_id, name, file_path, container_name, _now()),
            )
            bot_id = cursor.lastrowid
            await db.commit()
        assert bot_id is not None
        record = await self.get_bot_by_id(bot_id)
        assert record is not None
        return record

    async def update_bot_status(
        self,
        *,
        bot_id: int,
        status: str,
        container_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE bots
                SET status = ?,
                    container_id = COALESCE(?, container_id),
                    last_error = ?,
                    started_at = CASE WHEN ? = 'running' THEN ? ELSE started_at END,
                    stopped_at = CASE WHEN ? IN ('stopped', 'crashed', 'expired') THEN ? ELSE stopped_at END
                WHERE id = ?
                """,
                (
                    status,
                    container_id,
                    last_error,
                    status,
                    _now(),
                    status,
                    _now(),
                    bot_id,
                ),
            )
            await db.commit()

    async def replace_bot_file(self, *, bot_id: int, file_path: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE bots SET file_path = ? WHERE id = ?", (file_path, bot_id))
            await db.commit()

    async def set_container_name(self, *, bot_id: int, container_name: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE bots SET container_name = ? WHERE id = ?",
                (container_name, bot_id),
            )
            await db.commit()

    async def rename_bot(self, *, bot_id: int, new_name: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE bots SET name = ? WHERE id = ?", (new_name, bot_id))
            await db.commit()

    async def delete_bot(self, bot_id: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
            await db.commit()

    async def get_bot_by_id(self, bot_id: int) -> BotRecord | None:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                """
            SELECT id, tg_id, name, file_path, container_id, container_name, status,
                   started_at, stopped_at, last_error, created_at
            FROM bots WHERE id = ?
            """,
                (bot_id,),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_bot(row)

    async def get_bot_by_name(self, tg_id: int, name: str) -> BotRecord | None:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                """
            SELECT id, tg_id, name, file_path, container_id, container_name, status,
                   started_at, stopped_at, last_error, created_at
            FROM bots WHERE tg_id = ? AND name = ?
            """,
                (tg_id, name),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_bot(row)

    async def list_bots_for_user(self, tg_id: int) -> list[BotRecord]:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                """
            SELECT id, tg_id, name, file_path, container_id, container_name, status,
                   started_at, stopped_at, last_error, created_at
            FROM bots WHERE tg_id = ? ORDER BY created_at ASC
            """,
                (tg_id,),
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        return [_row_to_bot(row) for row in rows]

    async def list_running_bots(self) -> list[BotRecord]:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                """
            SELECT id, tg_id, name, file_path, container_id, container_name, status,
                   started_at, stopped_at, last_error, created_at
            FROM bots WHERE status = 'running'
            """
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        return [_row_to_bot(row) for row in rows]


def _row_to_bot(row: aiosqlite.Row | tuple) -> BotRecord:  # type: ignore[type-arg]
    created = _parse_dt(row[10])
    assert created is not None
    return BotRecord(
        id=int(row[0]),
        tg_id=int(row[1]),
        name=str(row[2]),
        file_path=str(row[3]),
        container_id=row[4],
        container_name=str(row[5]),
        status=str(row[6]),
        started_at=_parse_dt(row[7]),
        stopped_at=_parse_dt(row[8]),
        last_error=row[9],
        created_at=created,
    )
