"""SQLAlchemy ORM-модели."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    """Пользователь главного бота-конструктора."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bots: Mapped[list[ChildBot]] = relationship(back_populates="owner")


class ChildBot(Base, TimestampMixin):
    """Бот, созданный пользователем через конструктор."""

    __tablename__ = "child_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    bot_tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Сообщение приветствия (/start)
    start_text: Mapped[str | None] = mapped_column(Text)
    start_keyboard_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyboards.id", ondelete="SET NULL")
    )

    # Гейт подписки
    subscribe_channel: Mapped[str | None] = mapped_column(String(128))
    subscribe_link: Mapped[str | None] = mapped_column(String(256))

    # Антиспам: максимум сообщений в окне
    antispam_per_minute: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    owner: Mapped[User] = relationship(back_populates="bots")
    commands: Mapped[list[BotCommand]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    triggers: Mapped[list[BotTrigger]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    keyboards: Mapped[list[Keyboard]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
        foreign_keys="Keyboard.bot_id",
    )


class ChildBotUser(Base, TimestampMixin):
    """Пользователь, написавший дочернему боту (для рассылки/stats)."""

    __tablename__ = "child_bot_users"
    __table_args__ = (
        UniqueConstraint("bot_id", "tg_id", name="uq_child_bot_user"),
        Index("ix_child_bot_user_bot", "bot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("child_bots.id", ondelete="CASCADE"))
    tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Keyboard(Base, TimestampMixin):
    """Клавиатура — inline или reply.

    ``kind`` ∈ {``inline``, ``reply``}.
    """

    __tablename__ = "keyboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("child_bots.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    resize: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    one_time: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bot: Mapped[ChildBot] = relationship(back_populates="keyboards", foreign_keys=[bot_id])
    buttons: Mapped[list[KeyboardButton]] = relationship(
        back_populates="keyboard",
        cascade="all, delete-orphan",
        order_by="KeyboardButton.row, KeyboardButton.col",
    )


class KeyboardButton(Base):
    """Кнопка клавиатуры. Координаты ``row``/``col`` определяют размещение."""

    __tablename__ = "keyboard_buttons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyboard_id: Mapped[int] = mapped_column(
        ForeignKey("keyboards.id", ondelete="CASCADE"), index=True
    )
    row: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    col: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(String(128), nullable=False)
    # Только premium-эмодзи: id custom emoji
    icon_custom_emoji_id: Mapped[str | None] = mapped_column(String(64))
    # Тип действия для inline-кнопок: url | callback | open_keyboard | reply | none
    action: Mapped[str] = mapped_column(String(32), default="callback", nullable=False)
    # Содержимое для url/callback_data/имя клавиатуры/текст ответа
    payload: Mapped[str | None] = mapped_column(Text)

    keyboard: Mapped[Keyboard] = relationship(back_populates="buttons")


class BotCommand(Base, TimestampMixin):
    """Команда дочернего бота (например, ``/help``)."""

    __tablename__ = "bot_commands"
    __table_args__ = (
        UniqueConstraint("bot_id", "command", name="uq_bot_command"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("child_bots.id", ondelete="CASCADE"), index=True)
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(128))
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    keyboard_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyboards.id", ondelete="SET NULL")
    )

    bot: Mapped[ChildBot] = relationship(back_populates="commands")


class BotTrigger(Base, TimestampMixin):
    """Текстовый триггер: реакция на сообщение по совпадению."""

    __tablename__ = "bot_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("child_bots.id", ondelete="CASCADE"), index=True)
    # exact | contains | startswith
    match_type: Mapped[str] = mapped_column(String(16), default="exact", nullable=False)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    keyboard_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyboards.id", ondelete="SET NULL")
    )

    bot: Mapped[ChildBot] = relationship(back_populates="triggers")


class BroadcastLog(Base, TimestampMixin):
    """Журнал рассылок дочернего бота."""

    __tablename__ = "broadcast_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("child_bots.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0)
    delivered: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
