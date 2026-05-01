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
    plan_id TEXT NOT NULL DEFAULT '',
    mem_mb INTEGER NOT NULL DEFAULT 256,
    cpu_quota REAL NOT NULL DEFAULT 0.5,
    disk_mb INTEGER NOT NULL DEFAULT 100,
    fsize_mb INTEGER NOT NULL DEFAULT 50,
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
    plan_id TEXT NOT NULL DEFAULT '',
    mem_mb INTEGER NOT NULL DEFAULT 256,
    cpu_quota REAL NOT NULL DEFAULT 0.5,
    disk_mb INTEGER NOT NULL DEFAULT 100,
    fsize_mb INTEGER NOT NULL DEFAULT 50,
    UNIQUE(tg_id, name)
);
CREATE INDEX IF NOT EXISTS idx_bots_tg_id ON bots(tg_id);
"""

# Migrations applied on every init() to grow legacy schemas with the resource
# columns added in the resource-tier model. SQLite has no IF NOT EXISTS for
# ADD COLUMN, so we read existing columns first and only add what's missing.
_BOT_RESOURCE_COLUMNS: list[tuple[str, str]] = [
    ("plan_id", "TEXT NOT NULL DEFAULT ''"),
    ("mem_mb", "INTEGER NOT NULL DEFAULT 256"),
    ("cpu_quota", "REAL NOT NULL DEFAULT 0.5"),
    ("disk_mb", "INTEGER NOT NULL DEFAULT 100"),
    ("fsize_mb", "INTEGER NOT NULL DEFAULT 50"),
]
_SUB_RESOURCE_COLUMNS: list[tuple[str, str]] = list(_BOT_RESOURCE_COLUMNS)


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
    plan_id: str = ""
    mem_mb: int = 256
    cpu_quota: float = 0.5
    disk_mb: int = 100
    fsize_mb: int = 50

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
    plan_id: str = ""
    mem_mb: int = 256
    cpu_quota: float = 0.5
    disk_mb: int = 100
    fsize_mb: int = 50


class Database:
    """Thin async wrapper over a single SQLite file."""

    def __init__(self, path: Path):
        self._path = path

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(SCHEMA)
            await self._migrate_resource_columns(db, "bots", _BOT_RESOURCE_COLUMNS)
            await self._migrate_resource_columns(db, "subscriptions", _SUB_RESOURCE_COLUMNS)
            await db.commit()

    @staticmethod
    async def _migrate_resource_columns(
        db: aiosqlite.Connection,
        table: str,
        columns: list[tuple[str, str]],
    ) -> None:
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            existing_rows = await cur.fetchall()
        existing = {str(row[1]) for row in existing_rows}
        for col, decl in columns:
            if col in existing:
                continue
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

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
                """
                SELECT tg_id, expires_at, bot_quota, total_paid_stars,
                       plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb
                FROM subscriptions WHERE tg_id = ?
                """,
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
            plan_id=str(row[4] or ""),
            mem_mb=int(row[5]),
            cpu_quota=float(row[6]),
            disk_mb=int(row[7]),
            fsize_mb=int(row[8]),
        )

    async def apply_payment(
        self,
        *,
        tg_id: int,
        plan_id: str,
        paid_stars: int,
        days: int,
        bots: int,
        mem_mb: int,
        cpu_quota: float,
        disk_mb: int,
        fsize_mb: int,
        payment_charge_id: str | None,
    ) -> Subscription:
        """Apply a new payment to the user's subscription.

        Rules: expires_at = max(current, now) + days; resource fields take the
        max of (current, plan), so buying a smaller plan never downgrades.
        """

        now = datetime.now(UTC)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("BEGIN")
            try:
                async with db.execute(
                    """
                    SELECT expires_at, bot_quota, total_paid_stars,
                           plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb
                    FROM subscriptions WHERE tg_id = ?
                    """,
                    (tg_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    current_expiry = _parse_dt(row[0]) or now
                    base = current_expiry if current_expiry > now else now
                    new_expiry = base + timedelta(days=days)
                    new_quota = max(int(row[1]), bots)
                    new_total = int(row[2]) + paid_stars
                    new_mem = max(int(row[4]), mem_mb)
                    new_cpu = max(float(row[5]), cpu_quota)
                    new_disk = max(int(row[6]), disk_mb)
                    new_fsize = max(int(row[7]), fsize_mb)
                    new_plan_id = plan_id if new_mem == mem_mb else str(row[3] or plan_id)
                    await db.execute(
                        """
                        UPDATE subscriptions
                        SET expires_at = ?, bot_quota = ?, total_paid_stars = ?,
                            plan_id = ?, mem_mb = ?, cpu_quota = ?,
                            disk_mb = ?, fsize_mb = ?, updated_at = ?
                        WHERE tg_id = ?
                        """,
                        (
                            new_expiry.isoformat(),
                            new_quota,
                            new_total,
                            new_plan_id,
                            new_mem,
                            new_cpu,
                            new_disk,
                            new_fsize,
                            _now(),
                            tg_id,
                        ),
                    )
                else:
                    new_expiry = now + timedelta(days=days)
                    new_quota = bots
                    new_total = paid_stars
                    new_mem = mem_mb
                    new_cpu = cpu_quota
                    new_disk = disk_mb
                    new_fsize = fsize_mb
                    new_plan_id = plan_id
                    await db.execute(
                        """
                        INSERT INTO subscriptions (
                            tg_id, expires_at, bot_quota, total_paid_stars,
                            plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            tg_id,
                            new_expiry.isoformat(),
                            new_quota,
                            new_total,
                            new_plan_id,
                            new_mem,
                            new_cpu,
                            new_disk,
                            new_fsize,
                            _now(),
                        ),
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
            plan_id=new_plan_id,
            mem_mb=new_mem,
            cpu_quota=new_cpu,
            disk_mb=new_disk,
            fsize_mb=new_fsize,
        )

    async def list_active_subscriptions(self) -> list[Subscription]:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                """
            SELECT tg_id, expires_at, bot_quota, total_paid_stars,
                   plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb
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
                    plan_id=str(row[4] or ""),
                    mem_mb=int(row[5]),
                    cpu_quota=float(row[6]),
                    disk_mb=int(row[7]),
                    fsize_mb=int(row[8]),
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
        plan_id: str,
        mem_mb: int,
        cpu_quota: float,
        disk_mb: int,
        fsize_mb: int,
    ) -> BotRecord:
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """
                INSERT INTO bots (
                    tg_id, name, file_path, container_name, status, created_at,
                    plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb
                )
                VALUES (?, ?, ?, ?, 'stopped', ?, ?, ?, ?, ?, ?)
                """,
                (
                    tg_id,
                    name,
                    file_path,
                    container_name,
                    _now(),
                    plan_id,
                    mem_mb,
                    cpu_quota,
                    disk_mb,
                    fsize_mb,
                ),
            )
            bot_id = cursor.lastrowid
            await db.commit()
        assert bot_id is not None
        record = await self.get_bot_by_id(bot_id)
        assert record is not None
        return record

    async def update_bot_resources(
        self,
        *,
        bot_id: int,
        plan_id: str,
        mem_mb: int,
        cpu_quota: float,
        disk_mb: int,
        fsize_mb: int,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                UPDATE bots
                SET plan_id = ?, mem_mb = ?, cpu_quota = ?, disk_mb = ?, fsize_mb = ?
                WHERE id = ?
                """,
                (plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb, bot_id),
            )
            await db.commit()

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
            db.execute(_SELECT_BOT + " WHERE id = ?", (bot_id,)) as cursor,
        ):
            row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_bot(row)

    async def get_bot_by_name(self, tg_id: int, name: str) -> BotRecord | None:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(_SELECT_BOT + " WHERE tg_id = ? AND name = ?", (tg_id, name)) as cursor,
        ):
            row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_bot(row)

    async def list_bots_for_user(self, tg_id: int) -> list[BotRecord]:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(
                _SELECT_BOT + " WHERE tg_id = ? ORDER BY created_at ASC",
                (tg_id,),
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        return [_row_to_bot(row) for row in rows]

    async def list_running_bots(self) -> list[BotRecord]:
        async with (
            aiosqlite.connect(self._path) as db,
            db.execute(_SELECT_BOT + " WHERE status = 'running'") as cursor,
        ):
            rows = await cursor.fetchall()
        return [_row_to_bot(row) for row in rows]


_SELECT_BOT = """
SELECT id, tg_id, name, file_path, container_id, container_name, status,
       started_at, stopped_at, last_error, created_at,
       plan_id, mem_mb, cpu_quota, disk_mb, fsize_mb
FROM bots
"""


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
        plan_id=str(row[11] or ""),
        mem_mb=int(row[12]),
        cpu_quota=float(row[13]),
        disk_mb=int(row[14]),
        fsize_mb=int(row[15]),
    )
