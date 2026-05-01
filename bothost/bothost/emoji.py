"""Premium emoji helpers — wraps Telegram custom-emoji `<tg-emoji>` HTML tags.

Telegram Bot API supports custom emojis in two places:

1. **HTML message text** via the `<tg-emoji emoji-id="...">FALLBACK</tg-emoji>`
   tag. Telegram Premium users see the animated/custom emoji; non-premium users
   see the plain fallback character. Use the module-level `tg()` helper or any
   of the rendered constants (e.g. `e.SMILE`).

2. **Inline / reply keyboard buttons** via the `icon_custom_emoji_id` field
   (added in Bot API 9.4, requires aiogram >= 3.25). Only works when the bot's
   owner has Telegram Premium *or* the bot owns a Fragment-purchased username.
   Use the raw IDs from the `ID` class (e.g. `ID.SETTINGS`).
"""

from __future__ import annotations


def tg(emoji_id: str, fallback: str) -> str:
    """Render a `<tg-emoji>` HTML span for use inside a message text."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


class ID:
    """Raw custom-emoji IDs for `icon_custom_emoji_id` on keyboard buttons."""

    SETTINGS = "5870982283724328568"
    PROFILE = "5870994129244131212"
    PEOPLE = "5870772616305839506"
    PERSON_OK = "5891207662678317861"
    PERSON_BAD = "5893192487324880883"
    FILE = "5870528606328852614"
    SMILE = "5870764288364252592"
    GRAPH_UP = "5870930636742595124"
    STATS = "5870921681735781843"
    HOUSE = "5873147866364514353"
    LOCK_CLOSED = "6037249452824072506"
    LOCK_OPEN = "6037496202990194718"
    MEGAPHONE = "6039422865189638057"
    CHECK = "5870633910337015697"
    CROSS = "5870657884844462243"
    PENCIL = "5870676941614354370"
    TRASH = "5870875489362513438"
    DOWN = "5893057118545646106"
    PAPERCLIP = "6039451237743595514"
    LINK = "5769289093221454192"
    INFO = "6028435952299413210"
    BOT = "6030400221232501136"
    EYE = "6037397706505195857"
    EYE_HIDDEN = "6037243349675544634"
    SEND = "5963103826075456248"
    DOWNLOAD = "6039802767931871481"
    BELL = "6039486778597970865"
    GIFT = "6032644646587338669"
    CLOCK = "5983150113483134607"
    PARTY = "6041731551845159060"
    FONT = "5870801517140775623"
    WRITE = "5870753782874246579"
    MEDIA = "6035128606563241721"
    PIN = "6042011682497106307"
    WALLET = "5769126056262898415"
    BOX = "5884479287171485878"
    CRYPTOBOT = "5260752406890711732"
    CALENDAR = "5890937706803894250"
    TAG = "5886285355279193209"
    TIME_PASSED = "5775896410780079073"
    APPS = "5778672437122045013"
    BRUSH = "6050679691004612757"
    ADD_TEXT = "5771851822897566479"
    RESOLUTION = "5778479949572738874"
    COIN = "5904462880941545555"
    COIN_SEND = "5890848474563352982"
    COIN_RECV = "5879814368572478751"
    CODE = "5940433880585605708"
    LOADING = "5345906554510012647"


# --- pre-rendered HTML spans for message text (mapping from user-supplied list) ---
SETTINGS = tg(ID.SETTINGS, "⚙")
PROFILE = tg(ID.PROFILE, "👤")
PEOPLE = tg(ID.PEOPLE, "👥")
PERSON_OK = tg(ID.PERSON_OK, "👤")
PERSON_BAD = tg(ID.PERSON_BAD, "👤")
FILE = tg(ID.FILE, "📁")
SMILE = tg(ID.SMILE, "🙂")
GRAPH_UP = tg(ID.GRAPH_UP, "📊")
STATS = tg(ID.STATS, "📊")
HOUSE = tg(ID.HOUSE, "🏘")
LOCK_CLOSED = tg(ID.LOCK_CLOSED, "🔒")
LOCK_OPEN = tg(ID.LOCK_OPEN, "🔓")
MEGAPHONE = tg(ID.MEGAPHONE, "📣")
CHECK = tg(ID.CHECK, "✅")
CROSS = tg(ID.CROSS, "❌")
PENCIL = tg(ID.PENCIL, "🖋")
TRASH = tg(ID.TRASH, "🗑")
DOWN = tg(ID.DOWN, "📰")
PAPERCLIP = tg(ID.PAPERCLIP, "📎")
LINK = tg(ID.LINK, "🔗")
INFO = tg(ID.INFO, "ℹ")
BOT = tg(ID.BOT, "🤖")
EYE = tg(ID.EYE, "👁")
EYE_HIDDEN = tg(ID.EYE_HIDDEN, "👁")
SEND = tg(ID.SEND, "⬆")
DOWNLOAD = tg(ID.DOWNLOAD, "⬇")
BELL = tg(ID.BELL, "🔔")
GIFT = tg(ID.GIFT, "🎁")
CLOCK = tg(ID.CLOCK, "⏰")
PARTY = tg(ID.PARTY, "🎉")
FONT = tg(ID.FONT, "🔗")
WRITE = tg(ID.WRITE, "✍")
MEDIA = tg(ID.MEDIA, "🖼")
PIN = tg(ID.PIN, "📍")
WALLET = tg(ID.WALLET, "👛")
BOX = tg(ID.BOX, "📦")
CRYPTOBOT = tg(ID.CRYPTOBOT, "👾")
CALENDAR = tg(ID.CALENDAR, "📅")
TAG = tg(ID.TAG, "🏷")
TIME_PASSED = tg(ID.TIME_PASSED, "🕓")
APPS = tg(ID.APPS, "📦")
BRUSH = tg(ID.BRUSH, "🖌")
ADD_TEXT = tg(ID.ADD_TEXT, "🔡")
RESOLUTION = tg(ID.RESOLUTION, "↔")
COIN = tg(ID.COIN, "🪙")
COIN_SEND = tg(ID.COIN_SEND, "🪙")
COIN_RECV = tg(ID.COIN_RECV, "🏧")
CODE = tg(ID.CODE, "🔨")
LOADING = tg(ID.LOADING, "🔄")
