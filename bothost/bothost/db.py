"""Async SQLite storage for users, subscriptions and bots."""

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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    paid_stars INTEGER NOT NULL,
    payment_charge_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tg_id ON subscriptions(tg_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_expires_at ON subscriptions(expires_at);

CREATE TABLE IF NOT EXISTS bots (
    tg_id INTEGER PRIMARY KEY REFERENCES users(tg_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    container_id TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    stopped_at TEXT,
    last_error TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw)


@dataclass(slots=True)
class Subscription:
    id: int
    tg_id: int
    started_at: datetime
    expires_at: datetime
    paid_stars: int

    @property
    def is_active(self) -> bool:
        return self.expires_at > datetime.now(UTC)


@dataclass(slots=True)
class BotRecord:
    tg_id: int
    file_path: str
    container_id: str | None
    status: str  # "stopped" | "running" | "crashed" | "expired"
    started_at: datetime | None
    stopped_at: datetime | None
    last_error: str | None


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
        async with aiosqlite.connect(self._path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    # ---- subscriptions ----

    async def add_subscription(
        self,
        tg_id: int,
        days: int,
        paid_stars: int,
        payment_charge_id: str | None,
    ) -> Subscription:
        now = datetime.now(UTC)
        # extend from current expiration if still active, else from now
        active = await self.active_subscription(tg_id)
        starts_at = active.expires_at if active else now
        expires_at = starts_at + timedelta(days=days)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """
                INSERT INTO subscriptions (tg_id, started_at, expires_at, paid_stars, payment_charge_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tg_id,
                    starts_at.isoformat(),
                    expires_at.isoformat(),
                    paid_stars,
                    payment_charge_id,
                ),
            )
            sub_id = cursor.lastrowid
            await db.commit()
        assert sub_id is not None
        return Subscription(
            id=sub_id,
            tg_id=tg_id,
            started_at=starts_at,
            expires_at=expires_at,
            paid_stars=paid_stars,
        )

    async def active_subscription(self, tg_id: int) -> Subscription | None:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                """
                SELECT id, tg_id, started_at, expires_at, paid_stars
                FROM subscriptions
                WHERE tg_id = ? AND expires_at > ?
                ORDER BY expires_at DESC
                LIMIT 1
                """,
                (tg_id, _now()),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        started = _parse_dt(row[2])
        expires = _parse_dt(row[3])
        assert started is not None and expires is not None
        return Subscription(
            id=int(row[0]),
            tg_id=int(row[1]),
            started_at=started,
            expires_at=expires,
            paid_stars=int(row[4]),
        )

    async def list_active_subscriptions(self) -> list[Subscription]:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                """
                SELECT id, tg_id, started_at, expires_at, paid_stars
                FROM subscriptions
                WHERE expires_at > ?
                ORDER BY expires_at ASC
                """,
                (_now(),),
            ) as cursor:
                rows = await cursor.fetchall()
        result: list[Subscription] = []
        for row in rows:
            started = _parse_dt(row[2])
            expires = _parse_dt(row[3])
            assert started is not None and expires is not None
            result.append(
                Subscription(
                    id=int(row[0]),
                    tg_id=int(row[1]),
                    started_at=started,
                    expires_at=expires,
                    paid_stars=int(row[4]),
                )
            )
        return result

    async def total_paid_stars(self) -> int:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute("SELECT COALESCE(SUM(paid_stars), 0) FROM subscriptions") as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def extend_subscription(self, tg_id: int, days: int) -> Subscription:
        return await self.add_subscription(
            tg_id=tg_id, days=days, paid_stars=0, payment_charge_id=None
        )

    # ---- bots ----

    async def upsert_bot(
        self,
        tg_id: int,
        file_path: str,
        status: str,
        container_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = _now()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO bots (tg_id, file_path, container_id, status, started_at, stopped_at, last_error)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                    file_path = excluded.file_path,
                    container_id = excluded.container_id,
                    status = excluded.status,
                    started_at = CASE
                        WHEN excluded.status = 'running' THEN excluded.started_at
                        ELSE bots.started_at
                    END,
                    stopped_at = CASE
                        WHEN excluded.status IN ('stopped', 'crashed', 'expired') THEN excluded.started_at
                        ELSE bots.stopped_at
                    END,
                    last_error = excluded.last_error
                """,
                (tg_id, file_path, container_id, status, now, last_error),
            )
            await db.commit()

    async def get_bot(self, tg_id: int) -> BotRecord | None:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                """
                SELECT tg_id, file_path, container_id, status, started_at, stopped_at, last_error
                FROM bots WHERE tg_id = ?
                """,
                (tg_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return BotRecord(
            tg_id=int(row[0]),
            file_path=str(row[1]),
            container_id=row[2],
            status=str(row[3]),
            started_at=_parse_dt(row[4]),
            stopped_at=_parse_dt(row[5]),
            last_error=row[6],
        )

    async def list_running_bots(self) -> list[BotRecord]:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                """
                SELECT tg_id, file_path, container_id, status, started_at, stopped_at, last_error
                FROM bots WHERE status = 'running'
                """
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            BotRecord(
                tg_id=int(row[0]),
                file_path=str(row[1]),
                container_id=row[2],
                status=str(row[3]),
                started_at=_parse_dt(row[4]),
                stopped_at=_parse_dt(row[5]),
                last_error=row[6],
            )
            for row in rows
        ]
