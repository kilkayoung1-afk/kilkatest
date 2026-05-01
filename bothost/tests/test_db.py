"""Smoke tests for the SQLite layer."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bothost.db import Database
from bothost.validator import validate_user_script


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite3"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.get_event_loop().run_until_complete(coro)


def test_subscription_lifecycle(db_path: Path) -> None:
    async def scenario() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(tg_id=1, username="alice")

        assert await db.active_subscription(1) is None

        sub = await db.add_subscription(tg_id=1, days=7, paid_stars=50, payment_charge_id="ch1")
        assert sub.is_active
        assert (sub.expires_at - sub.started_at) == timedelta(days=7)

        active = await db.active_subscription(1)
        assert active is not None and active.id == sub.id

        # Extending stacks on top of remaining time
        sub2 = await db.add_subscription(tg_id=1, days=7, paid_stars=50, payment_charge_id="ch2")
        assert sub2.expires_at - sub.expires_at == timedelta(days=7)

        assert await db.total_paid_stars() == 100
        assert await db.count_users() == 1

    asyncio.run(scenario())


def test_extend_admin_action(db_path: Path) -> None:
    async def scenario() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(tg_id=42, username=None)
        sub = await db.extend_subscription(42, 3)
        assert sub.paid_stars == 0
        assert sub.expires_at > datetime.now(UTC) + timedelta(days=2, hours=23)

    asyncio.run(scenario())


def test_bot_record_upsert(db_path: Path) -> None:
    async def scenario() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(tg_id=7, username="bob")
        await db.upsert_bot(tg_id=7, file_path="/x/bot.py", status="running", container_id="cid1")
        record = await db.get_bot(7)
        assert record is not None
        assert record.status == "running"
        assert record.container_id == "cid1"

        await db.upsert_bot(tg_id=7, file_path="/x/bot.py", status="stopped", container_id=None)
        record = await db.get_bot(7)
        assert record is not None and record.status == "stopped"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "source,ok",
    [
        (b"print('hi')\n", True),
        (b"def x():\n    pass\n", True),
        (b"\xff\xfe not utf-8 \xfd", False),
        (b"def(\n", False),
    ],
)
def test_validator(source: bytes, ok: bool) -> None:
    assert validate_user_script(source).ok is ok


def test_validator_warns_on_eval() -> None:
    result = validate_user_script(b"eval('1+1')\n")
    assert result.ok
    assert result.warnings is not None and any("eval" in w for w in result.warnings)
