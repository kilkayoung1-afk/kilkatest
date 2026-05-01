"""Async tests for the storage layer."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bothost.db import Database
from bothost.plans import Plan, find_plan, parse_plans
from bothost.runner import slug_name
from bothost.validator import validate_user_script


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "bothost.sqlite3"


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_subscription_lifecycle(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(1, "alice")

        sub = await db.get_subscription(1)
        assert sub is None

        sub = await db.apply_payment(
            tg_id=1, plan_id="start", paid_stars=50, days=14, bots=1, payment_charge_id="x"
        )
        assert sub.bot_quota == 1
        assert sub.total_paid_stars == 50
        assert sub.expires_at > datetime.now(UTC)

        # second payment of a bigger plan stacks days and increases quota
        sub2 = await db.apply_payment(
            tg_id=1, plan_id="plus", paid_stars=130, days=14, bots=3, payment_charge_id="y"
        )
        assert sub2.bot_quota == 3
        assert sub2.total_paid_stars == 50 + 130
        assert sub2.expires_at > sub.expires_at + timedelta(days=13)

    run(go())


def test_apply_payment_when_expired_starts_from_now(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(2, "bob")

        sub = await db.apply_payment(
            tg_id=2, plan_id="start", paid_stars=50, days=14, bots=1, payment_charge_id=None
        )
        # force-expire
        import aiosqlite

        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                "UPDATE subscriptions SET expires_at = ? WHERE tg_id = ?",
                ((datetime.now(UTC) - timedelta(days=1)).isoformat(), 2),
            )
            await conn.commit()
        sub2 = await db.apply_payment(
            tg_id=2, plan_id="start", paid_stars=50, days=14, bots=1, payment_charge_id=None
        )
        assert sub2.expires_at > datetime.now(UTC) + timedelta(days=13)

        _ = sub  # silence unused

    run(go())


def test_total_paid_stars(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(3, "c")
        await db.apply_payment(
            tg_id=3, plan_id="start", paid_stars=50, days=14, bots=1, payment_charge_id=None
        )
        await db.apply_payment(
            tg_id=3, plan_id="plus", paid_stars=130, days=14, bots=3, payment_charge_id=None
        )
        assert await db.total_paid_stars() == 50 + 130

    run(go())


def test_bot_crud(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(10, "dave")
        rec = await db.create_bot(
            tg_id=10, name="bot1", file_path="/tmp/bot.py", container_name="placeholder_1"
        )
        assert rec.status == "stopped"
        await db.set_container_name(bot_id=rec.id, container_name="bothost_user_10_1")
        await db.update_bot_status(bot_id=rec.id, status="running", container_id="abc")
        fresh = await db.get_bot_by_id(rec.id)
        assert fresh is not None
        assert fresh.status == "running"
        assert fresh.container_id == "abc"
        assert fresh.container_name == "bothost_user_10_1"

        same = await db.get_bot_by_name(10, "bot1")
        assert same is not None and same.id == rec.id

        await db.rename_bot(bot_id=rec.id, new_name="bot1_renamed")
        bots = await db.list_bots_for_user(10)
        assert len(bots) == 1 and bots[0].name == "bot1_renamed"

        await db.delete_bot(rec.id)
        assert await db.get_bot_by_id(rec.id) is None

    run(go())


def test_admin_extend(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(20, "x")
        sub = await db.apply_payment(
            tg_id=20, plan_id="admin", paid_stars=0, days=7, bots=2, payment_charge_id=None
        )
        assert sub.total_paid_stars == 0
        assert sub.bot_quota == 2
        assert sub.expires_at > datetime.now(UTC) + timedelta(days=6)

    run(go())


def test_plans_default() -> None:
    plans = parse_plans(None)
    assert any(p.id == "start" and p.stars == 50 for p in plans)
    assert find_plan(plans, "max") is not None


def test_plan_label_format() -> None:
    plan = Plan(id="start", name="Старт", stars=50, days=14, bots=1)
    assert "50⭐" in plan.label()
    assert "14 дн" in plan.label()


@pytest.mark.parametrize(
    "name,ok",
    [
        ("bot1", True),
        ("my-bot_2", True),
        ("a" * 32, True),
        ("a" * 33, False),
        ("", False),
        ("with space", False),
        ("кир", False),
    ],
)
def test_slug_name(name: str, ok: bool) -> None:
    assert (slug_name(name) is not None) == ok


@pytest.mark.parametrize(
    "source,ok",
    [
        (b"print('hi')", True),
        (b"\xff\xfe garbage", False),
        (b"def f(:\n  pass\n", False),
        (b"x" * (2 * 1024 * 1024), False),
    ],
)
def test_validator(source: bytes, ok: bool) -> None:
    result = validate_user_script(source)
    assert result.ok == ok


def test_validator_warns_on_eval() -> None:
    result = validate_user_script(b"eval('1+1')\n")
    assert result.ok
    assert any("eval" in w for w in result.warnings)
