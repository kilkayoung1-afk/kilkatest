"""Репозиторные функции (data access) поверх ORM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from telegram_bot_constructor.db.models import (
    BotCommand,
    BotTrigger,
    BroadcastLog,
    ChildBot,
    ChildBotUser,
    Keyboard,
    KeyboardButton,
    User,
)

# ---------- Users ----------------------------------------------------------


async def get_or_create_user(
    session: AsyncSession,
    *,
    tg_id: int,
    username: str | None,
    first_name: str | None,
) -> User:
    res = await session.execute(select(User).where(User.tg_id == tg_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(tg_id=tg_id, username=username, first_name=first_name)
        session.add(user)
        await session.flush()
    else:
        changed = False
        if user.username != username:
            user.username = username
            changed = True
        if user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if changed:
            await session.flush()
    return user


# ---------- Child bots -----------------------------------------------------


async def list_user_bots(session: AsyncSession, user_id: int) -> list[ChildBot]:
    res = await session.execute(
        select(ChildBot).where(ChildBot.owner_id == user_id).order_by(ChildBot.id)
    )
    return list(res.scalars().all())


async def count_user_bots(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.count(ChildBot.id)).where(ChildBot.owner_id == user_id)
    )
    return int(res.scalar_one())


async def get_bot_by_id(session: AsyncSession, bot_id: int) -> ChildBot | None:
    res = await session.execute(
        select(ChildBot).where(ChildBot.id == bot_id).options(selectinload(ChildBot.owner))
    )
    return res.scalar_one_or_none()


async def get_bot_by_token(session: AsyncSession, token: str) -> ChildBot | None:
    res = await session.execute(
        select(ChildBot).where(ChildBot.token == token).options(selectinload(ChildBot.owner))
    )
    return res.scalar_one_or_none()


async def get_all_active_bots(session: AsyncSession) -> list[ChildBot]:
    res = await session.execute(select(ChildBot).where(ChildBot.is_active.is_(True)))
    return list(res.scalars().all())


async def create_bot(
    session: AsyncSession,
    *,
    owner_id: int,
    token: str,
    bot_tg_id: int,
    username: str | None,
    title: str | None,
) -> ChildBot:
    bot = ChildBot(
        owner_id=owner_id,
        token=token,
        bot_tg_id=bot_tg_id,
        username=username,
        title=title,
        start_text="Привет! Я работаю на конструкторе ботов.",
    )
    session.add(bot)
    await session.flush()
    return bot


async def delete_bot(session: AsyncSession, bot_id: int) -> None:
    bot = await get_bot_by_id(session, bot_id)
    if bot is not None:
        await session.delete(bot)


async def set_bot_active(session: AsyncSession, bot_id: int, active: bool) -> None:
    await session.execute(
        update(ChildBot).where(ChildBot.id == bot_id).values(is_active=active)
    )


# ---------- Child bot users -----------------------------------------------


async def upsert_child_user(
    session: AsyncSession,
    *,
    bot_id: int,
    tg_id: int,
    username: str | None,
    first_name: str | None,
) -> ChildBotUser:
    res = await session.execute(
        select(ChildBotUser).where(
            ChildBotUser.bot_id == bot_id, ChildBotUser.tg_id == tg_id
        )
    )
    user = res.scalar_one_or_none()
    if user is None:
        user = ChildBotUser(
            bot_id=bot_id, tg_id=tg_id, username=username, first_name=first_name
        )
        session.add(user)
        await session.flush()
    else:
        user.username = username
        user.first_name = first_name
        user.last_seen_at = datetime.now(timezone.utc)
        await session.flush()
    return user


async def child_user_count(session: AsyncSession, bot_id: int) -> int:
    res = await session.execute(
        select(func.count(ChildBotUser.id)).where(ChildBotUser.bot_id == bot_id)
    )
    return int(res.scalar_one())


async def child_user_active_24h(session: AsyncSession, bot_id: int) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    res = await session.execute(
        select(func.count(ChildBotUser.id)).where(
            ChildBotUser.bot_id == bot_id, ChildBotUser.last_seen_at >= threshold
        )
    )
    return int(res.scalar_one())


async def list_child_users(session: AsyncSession, bot_id: int) -> list[ChildBotUser]:
    res = await session.execute(
        select(ChildBotUser).where(
            ChildBotUser.bot_id == bot_id, ChildBotUser.is_banned.is_(False)
        )
    )
    return list(res.scalars().all())


# ---------- Commands -------------------------------------------------------


async def list_commands(session: AsyncSession, bot_id: int) -> list[BotCommand]:
    res = await session.execute(
        select(BotCommand).where(BotCommand.bot_id == bot_id).order_by(BotCommand.id)
    )
    return list(res.scalars().all())


async def get_command(
    session: AsyncSession, bot_id: int, command: str
) -> BotCommand | None:
    res = await session.execute(
        select(BotCommand).where(
            BotCommand.bot_id == bot_id, BotCommand.command == command
        )
    )
    return res.scalar_one_or_none()


async def get_command_by_id(session: AsyncSession, cmd_id: int) -> BotCommand | None:
    res = await session.execute(select(BotCommand).where(BotCommand.id == cmd_id))
    return res.scalar_one_or_none()


async def create_command(
    session: AsyncSession,
    *,
    bot_id: int,
    command: str,
    response_text: str,
    description: str | None = None,
) -> BotCommand:
    cmd = BotCommand(
        bot_id=bot_id,
        command=command,
        response_text=response_text,
        description=description,
    )
    session.add(cmd)
    await session.flush()
    return cmd


async def delete_command(session: AsyncSession, cmd_id: int) -> None:
    cmd = await get_command_by_id(session, cmd_id)
    if cmd is not None:
        await session.delete(cmd)


# ---------- Triggers -------------------------------------------------------


async def list_triggers(session: AsyncSession, bot_id: int) -> list[BotTrigger]:
    res = await session.execute(
        select(BotTrigger).where(BotTrigger.bot_id == bot_id).order_by(BotTrigger.id)
    )
    return list(res.scalars().all())


async def create_trigger(
    session: AsyncSession,
    *,
    bot_id: int,
    pattern: str,
    response_text: str,
    match_type: str = "exact",
) -> BotTrigger:
    trig = BotTrigger(
        bot_id=bot_id,
        pattern=pattern,
        response_text=response_text,
        match_type=match_type,
    )
    session.add(trig)
    await session.flush()
    return trig


async def get_trigger_by_id(session: AsyncSession, trig_id: int) -> BotTrigger | None:
    res = await session.execute(select(BotTrigger).where(BotTrigger.id == trig_id))
    return res.scalar_one_or_none()


async def delete_trigger(session: AsyncSession, trig_id: int) -> None:
    trig = await get_trigger_by_id(session, trig_id)
    if trig is not None:
        await session.delete(trig)


# ---------- Keyboards ------------------------------------------------------


async def list_keyboards(
    session: AsyncSession, bot_id: int, kind: str | None = None
) -> list[Keyboard]:
    stmt = select(Keyboard).where(Keyboard.bot_id == bot_id)
    if kind:
        stmt = stmt.where(Keyboard.kind == kind)
    stmt = stmt.order_by(Keyboard.id)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_keyboard(session: AsyncSession, kb_id: int) -> Keyboard | None:
    res = await session.execute(select(Keyboard).where(Keyboard.id == kb_id))
    return res.scalar_one_or_none()


async def create_keyboard(
    session: AsyncSession,
    *,
    bot_id: int,
    kind: str,
    title: str,
) -> Keyboard:
    kb = Keyboard(bot_id=bot_id, kind=kind, title=title)
    session.add(kb)
    await session.flush()
    return kb


async def delete_keyboard(session: AsyncSession, kb_id: int) -> None:
    kb = await get_keyboard(session, kb_id)
    if kb is not None:
        await session.delete(kb)


async def add_button(
    session: AsyncSession,
    *,
    keyboard_id: int,
    text: str,
    icon_custom_emoji_id: str | None,
    action: str,
    payload: str | None,
    row: int = 0,
    col: int = 0,
) -> KeyboardButton:
    btn = KeyboardButton(
        keyboard_id=keyboard_id,
        text=text,
        icon_custom_emoji_id=icon_custom_emoji_id,
        action=action,
        payload=payload,
        row=row,
        col=col,
    )
    session.add(btn)
    await session.flush()
    return btn


async def delete_button(session: AsyncSession, btn_id: int) -> None:
    res = await session.execute(
        select(KeyboardButton).where(KeyboardButton.id == btn_id)
    )
    btn = res.scalar_one_or_none()
    if btn is not None:
        await session.delete(btn)


# ---------- Broadcast ------------------------------------------------------


async def log_broadcast(
    session: AsyncSession,
    *,
    bot_id: int,
    text: str,
    total: int,
    delivered: int,
    failed: int,
) -> BroadcastLog:
    log = BroadcastLog(
        bot_id=bot_id,
        text=text,
        total=total,
        delivered=delivered,
        failed=failed,
    )
    session.add(log)
    await session.flush()
    return log
