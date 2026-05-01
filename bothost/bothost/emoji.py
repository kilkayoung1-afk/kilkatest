"""Premium emoji helpers — wraps Telegram custom-emoji `<tg-emoji>` HTML tags.

Telegram Bot API supports custom emojis only in HTML message text via the
`<tg-emoji emoji-id="...">FALLBACK</tg-emoji>` tag. Telegram Premium users see
the animated/custom emoji; non-premium users see the plain fallback character.

`InlineKeyboardButton.text` does NOT support custom emojis (Bot API limitation),
so for buttons we just emit the plain emoji from the constants below.
"""

from __future__ import annotations


def tg(emoji_id: str, fallback: str) -> str:
    """Render a `<tg-emoji>` HTML span."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# --- mapping from user-supplied list ---
SETTINGS = tg("5870982283724328568", "⚙")
PROFILE = tg("5870994129244131212", "👤")
PEOPLE = tg("5870772616305839506", "👥")
PERSON_OK = tg("5891207662678317861", "👤")
PERSON_BAD = tg("5893192487324880883", "👤")
FILE = tg("5870528606328852614", "📁")
SMILE = tg("5870764288364252592", "🙂")
GRAPH_UP = tg("5870930636742595124", "📊")
STATS = tg("5870921681735781843", "📊")
HOUSE = tg("5873147866364514353", "🏘")
LOCK_CLOSED = tg("6037249452824072506", "🔒")
LOCK_OPEN = tg("6037496202990194718", "🔓")
MEGAPHONE = tg("6039422865189638057", "📣")
CHECK = tg("5870633910337015697", "✅")
CROSS = tg("5870657884844462243", "❌")
PENCIL = tg("5870676941614354370", "🖋")
TRASH = tg("5870875489362513438", "🗑")
DOWN = tg("5893057118545646106", "📰")
PAPERCLIP = tg("6039451237743595514", "📎")
LINK = tg("5769289093221454192", "🔗")
INFO = tg("6028435952299413210", "ℹ")
BOT = tg("6030400221232501136", "🤖")
EYE = tg("6037397706505195857", "👁")
EYE_HIDDEN = tg("6037243349675544634", "👁")
SEND = tg("5963103826075456248", "⬆")
DOWNLOAD = tg("6039802767931871481", "⬇")
BELL = tg("6039486778597970865", "🔔")
GIFT = tg("6032644646587338669", "🎁")
CLOCK = tg("5983150113483134607", "⏰")
PARTY = tg("6041731551845159060", "🎉")
FONT = tg("5870801517140775623", "🔗")
WRITE = tg("5870753782874246579", "✍")
MEDIA = tg("6035128606563241721", "🖼")
PIN = tg("6042011682497106307", "📍")
WALLET = tg("5769126056262898415", "👛")
BOX = tg("5884479287171485878", "📦")
CRYPTOBOT = tg("5260752406890711732", "👾")
CALENDAR = tg("5890937706803894250", "📅")
TAG = tg("5886285355279193209", "🏷")
TIME_PASSED = tg("5775896410780079073", "🕓")
APPS = tg("5778672437122045013", "📦")
BRUSH = tg("6050679691004612757", "🖌")
ADD_TEXT = tg("5771851822897566479", "🔡")
RESOLUTION = tg("5778479949572738874", "↔")
COIN = tg("5904462880941545555", "🪙")
COIN_SEND = tg("5890848474563352982", "🪙")
COIN_RECV = tg("5879814368572478751", "🏧")
CODE = tg("5940433880585605708", "🔨")
LOADING = tg("5345906554510012647", "🔄")
