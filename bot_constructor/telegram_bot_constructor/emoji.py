"""Каталог premium-эмодзи и хелперы для рендера сообщений и кнопок.

Все эмодзи Telegram premium указываются по `custom_emoji_id`. Для текста
сообщений используется тег ``<tg-emoji emoji-id="...">FALLBACK</tg-emoji>`` (HTML).
Для inline / reply кнопок используется поле ``icon_custom_emoji_id``.

Этот модуль — **единственное** место, где должны храниться id; остальные модули
обращаются к константам по имени.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PremiumEmoji:
    """Описание premium-эмодзи: id для Telegram + fallback-символ."""

    emoji_id: str
    fallback: str

    def html(self) -> str:
        """Вернёт HTML-тег для использования в тексте сообщений."""
        return f'<tg-emoji emoji-id="{self.emoji_id}">{self.fallback}</tg-emoji>'

    def __str__(self) -> str:  # для удобства f-строк
        return self.html()


# --- Каталог premium-эмодзи (взят из ТЗ пользователя) ----------------------

E_SETTINGS = PremiumEmoji("5870982283724328568", "⚙")
E_PROFILE = PremiumEmoji("5870994129244131212", "👤")
E_PEOPLE = PremiumEmoji("5870772616305839506", "👥")
E_PERSON_CHECK = PremiumEmoji("5891207662678317861", "👤")
E_PERSON_CROSS = PremiumEmoji("5893192487324880883", "👤")
E_FILE = PremiumEmoji("5870528606328852614", "📁")
E_SMILE = PremiumEmoji("5870764288364252592", "🙂")
E_GRAPH_UP = PremiumEmoji("5870930636742595124", "📊")
E_STATS = PremiumEmoji("5870921681735781843", "📊")
E_HOUSE = PremiumEmoji("5873147866364514353", "🏘")
E_LOCK_CLOSED = PremiumEmoji("6037249452824072506", "🔒")
E_LOCK_OPEN = PremiumEmoji("6037496202990194718", "🔓")
E_MEGAPHONE = PremiumEmoji("6039422865189638057", "📣")
E_CHECK = PremiumEmoji("5870633910337015697", "✅")
E_CROSS = PremiumEmoji("5870657884844462243", "❌")
E_PENCIL = PremiumEmoji("5870676941614354370", "🖋")
E_TRASH = PremiumEmoji("5870875489362513438", "🗑")
E_DOWN = PremiumEmoji("5893057118545646106", "📰")
E_PAPERCLIP = PremiumEmoji("6039451237743595514", "📎")
E_LINK = PremiumEmoji("5769289093221454192", "🔗")
E_INFO = PremiumEmoji("6028435952299413210", "ℹ")
E_BOT = PremiumEmoji("6030400221232501136", "🤖")
E_EYE = PremiumEmoji("6037397706505195857", "👁")
E_EYE_HIDDEN = PremiumEmoji("6037243349675544634", "👁")
E_SEND_UP = PremiumEmoji("5963103826075456248", "⬆")
E_DOWNLOAD = PremiumEmoji("6039802767931871481", "⬇")
E_BELL = PremiumEmoji("6039486778597970865", "🔔")
E_GIFT = PremiumEmoji("6032644646587338669", "🎁")
E_CLOCK = PremiumEmoji("5983150113483134607", "⏰")
E_PARTY = PremiumEmoji("6041731551845159060", "🎉")
E_FONT = PremiumEmoji("5870801517140775623", "🔗")
E_WRITE = PremiumEmoji("5870753782874246579", "✍")
E_MEDIA = PremiumEmoji("6035128606563241721", "🖼")
E_GEO = PremiumEmoji("6042011682497106307", "📍")
E_WALLET = PremiumEmoji("5769126056262898415", "👛")
E_BOX = PremiumEmoji("5884479287171485878", "📦")
E_CRYPTO_BOT = PremiumEmoji("5260752406890711732", "👾")
E_CALENDAR = PremiumEmoji("5890937706803894250", "📅")
E_TAG = PremiumEmoji("5886285355279193209", "🏷")
E_TIME_PASSED = PremiumEmoji("5775896410780079073", "🕓")
E_APPS = PremiumEmoji("5778672437122045013", "📦")
E_BRUSH = PremiumEmoji("6050679691004612757", "🖌")
E_ADD_TEXT = PremiumEmoji("5771851822897566479", "🔡")
E_RESIZE = PremiumEmoji("5778479949572738874", "↔")
E_MONEY = PremiumEmoji("5904462880941545555", "🪙")
E_MONEY_SEND = PremiumEmoji("5890848474563352982", "🪙")
E_MONEY_RECV = PremiumEmoji("5879814368572478751", "🏧")
E_CODE = PremiumEmoji("5940433880585605708", "🔨")
E_LOADING = PremiumEmoji("5345906554510012647", "🔄")

# Алиасы по названиям из ТЗ
EMOJI_BY_NAME: dict[str, PremiumEmoji] = {
    "settings": E_SETTINGS,
    "profile": E_PROFILE,
    "people": E_PEOPLE,
    "person_check": E_PERSON_CHECK,
    "person_cross": E_PERSON_CROSS,
    "file": E_FILE,
    "smile": E_SMILE,
    "graph_up": E_GRAPH_UP,
    "stats": E_STATS,
    "house": E_HOUSE,
    "lock_closed": E_LOCK_CLOSED,
    "lock_open": E_LOCK_OPEN,
    "megaphone": E_MEGAPHONE,
    "check": E_CHECK,
    "cross": E_CROSS,
    "pencil": E_PENCIL,
    "trash": E_TRASH,
    "down": E_DOWN,
    "paperclip": E_PAPERCLIP,
    "link": E_LINK,
    "info": E_INFO,
    "bot": E_BOT,
    "eye": E_EYE,
    "eye_hidden": E_EYE_HIDDEN,
    "send": E_SEND_UP,
    "download": E_DOWNLOAD,
    "bell": E_BELL,
    "gift": E_GIFT,
    "clock": E_CLOCK,
    "party": E_PARTY,
    "font": E_FONT,
    "write": E_WRITE,
    "media": E_MEDIA,
    "geo": E_GEO,
    "wallet": E_WALLET,
    "box": E_BOX,
    "crypto_bot": E_CRYPTO_BOT,
    "calendar": E_CALENDAR,
    "tag": E_TAG,
    "time_passed": E_TIME_PASSED,
    "apps": E_APPS,
    "brush": E_BRUSH,
    "add_text": E_ADD_TEXT,
    "resize": E_RESIZE,
    "money": E_MONEY,
    "money_send": E_MONEY_SEND,
    "money_recv": E_MONEY_RECV,
    "code": E_CODE,
    "loading": E_LOADING,
}


def get_emoji(name: str) -> PremiumEmoji | None:
    """Найти эмодзи по короткому имени (см. ``EMOJI_BY_NAME``)."""
    return EMOJI_BY_NAME.get(name)


def get_emoji_by_id(emoji_id: str) -> PremiumEmoji | None:
    for em in EMOJI_BY_NAME.values():
        if em.emoji_id == emoji_id:
            return em
    return None
