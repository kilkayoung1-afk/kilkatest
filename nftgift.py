# meta name: NFTGift
# requires: aiohttp lottie fonttools cairosvg Pillow numpy

"""
NFT Gift caption module for Hikka userbot.

Скачивает Lottie-анимацию NFT-подарка Telegram (например, t.me/nft/PlushPepe-100),
сам выбирает на анимации лучшее место для подписи (например, на сердечке у Plush Pepe),
аккуратно вписывает туда твой текст, отправляет результат анимированным стикером
и автоматически добавляет его в твой личный стикерпак (создаст при первом
вызове, без помощи бота @Stickers).
"""

import asyncio
import gzip
import io
import json
import logging
import re
import subprocess

import aiohttp
from telethon.errors.rpcerrorlist import (
    StickersetInvalidError,
    ShortnameOccupyFailedError,
)
from telethon.tl.functions.messages import GetStickerSetRequest, UploadMediaRequest
from telethon.tl.functions.stickers import (
    AddStickerToSetRequest,
    CreateStickerSetRequest,
)
from telethon.tl.types import (
    DocumentAttributeFilename,
    InputDocument,
    InputMediaUploadedDocument,
    InputPeerSelf,
    InputStickerSetItem,
    InputStickerSetShortName,
    InputUserSelf,
    Message,
)

from .. import loader, utils

logger = logging.getLogger(__name__)

NFT_LINK_RE = re.compile(r"(?:https?://)?t\.me/nft/([\w\-]+)", re.IGNORECASE)
TGS_URL_RE = re.compile(r'(https://cdn\d*\.telesco\.pe/file/sticker\.tgs\?token=[^"\']+)')

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
MAX_TGS_SIZE = 64 * 1024  # Telegram sticker limit
CANVAS = 512
ANALYZE_SIZE = 96  # downscale used for image analysis
_SMART_MIN_SCORE = 0.45  # threshold below which we fall back to meme caption
_SMART_MIN_SIZE = 56  # smallest font size we consider in smart mode (smaller → fallback)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — independent from Hikka so they can be unit-tested.
# ─────────────────────────────────────────────────────────────────────────────


def _hex_to_rgb(value: str) -> tuple:
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Invalid HEX color: {value!r}")
    return (
        int(s[0:2], 16) / 255.0,
        int(s[2:4], 16) / 255.0,
        int(s[4:6], 16) / 255.0,
    )


def _parse_link(text: str):
    m = NFT_LINK_RE.search(text)
    return m.group(1) if m else None


def _render_frame(anim, size: int):
    """Render a middle frame of a Lottie animation to a PIL.Image (RGBA)."""
    from lottie.exporters.cairo import export_svg
    from PIL import Image

    mid = int((anim.in_point + anim.out_point) / 2)
    buf = io.StringIO()
    export_svg(anim, buf, frame=mid)
    svg = buf.getvalue()
    try:
        import cairosvg

        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    except Exception:
        # Fallback: try the system rsvg-convert binary if present.
        png = subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size)],
            input=svg.encode(),
            capture_output=True,
            check=True,
        ).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _box_sum(ii, y0, x0, y1, x1):
    return float(ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0])


def _build_integrals(img):
    """Pre-compute integral images of brightness, brightness² and alpha."""
    import numpy as np

    arr = np.array(img)
    rgb = arr[..., :3].astype(np.float32) / 255.0
    alpha = arr[..., 3].astype(np.float32) / 255.0
    brightness = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    h, w = brightness.shape

    def integral(a):
        out = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
        out[1:, 1:] = np.cumsum(np.cumsum(a, axis=0), axis=1)
        return out

    return integral(brightness), integral(brightness * brightness), integral(alpha), h, w


def _best_position_for(
    integrals,
    text_w: float,
    text_h: float,
    *,
    canvas: int,
    padding: float = 0.10,
    min_coverage: float = 0.92,
):
    """
    Scan the analysis bitmap for the best canvas position to place a
    `text_w × text_h` rectangle (in canvas pixels). The score rewards smooth
    (low pixel-brightness variance) and high-contrast (very dark / very light)
    backgrounds that lie fully on the sticker.

    Returns ``(score, cx, cy, mean_brightness)`` in canvas coordinates, or
    ``None`` if the rectangle does not fit anywhere with the required alpha
    coverage.
    """
    ii_b, ii_b2, ii_a, h, w = integrals
    s = w / canvas
    bw = max(4, int(text_w * (1 + padding) * s))
    bh = max(4, int(text_h * (1 + padding) * s))
    if bw > w or bh > h:
        return None

    n = bh * bw
    best = None
    for y0 in range(0, h - bh + 1, 2):
        for x0 in range(0, w - bw + 1, 2):
            cov = _box_sum(ii_a, y0, x0, y0 + bh, x0 + bw) / n
            if cov < min_coverage:
                continue
            sb = _box_sum(ii_b, y0, x0, y0 + bh, x0 + bw)
            sb2 = _box_sum(ii_b2, y0, x0, y0 + bh, x0 + bw)
            mean = sb / n
            std = max(0.0, sb2 / n - mean * mean) ** 0.5
            smooth = 1.0 - min(std * 5, 1.0)
            contrast = abs(mean - 0.5) * 2.0
            score = smooth * 0.5 + contrast * 0.5
            if best is None or score > best[0]:
                cx = (x0 + bw / 2) / s
                cy = (y0 + bh / 2) / s
                best = (score, cx, cy, mean)
    return best


def _render_caption(
    tgs_bytes: bytes,
    text: str,
    *,
    font: str,
    initial_size: int,
    fill_hex: str,
    stroke_hex: str,
    y_offset: int,
    max_width_ratio: float,
    smart: bool,
    auto_color: bool,
) -> bytes:
    """
    Add a text caption to a .tgs sticker.

    Two modes:

    * `smart=True` — render the middle frame as a small RGBA bitmap, then for
      each candidate font size (largest first) look for a position on the
      sticker where the text rectangle would sit on a smooth, high-contrast
      area. The first size whose best score clears `_SMART_MIN_SCORE` wins.
      If no size scores well enough, fall back to the meme-caption path below.

    * `smart=False` (or fallback) — classic meme caption: centre the text
      horizontally and place it near the bottom of the canvas (at the largest
      font size that still fits). When `smart=False` is requested explicitly,
      the user-configured `y_offset` and `max_width_ratio` are honoured.

    When `auto_color` is True and the smart path picks a *light* region, the
    fill and stroke colours are swapped so the text remains legible.
    """
    from lottie.exporters import export_tgs
    from lottie.objects import Color, Fill, ShapeLayer, Stroke
    from lottie.parsers.tgs import parse_tgs
    from lottie.utils.font import FontStyle

    anim = parse_tgs(io.BytesIO(tgs_bytes))
    canvas_w = int(anim.width)
    canvas_h = int(anim.height)

    initial = max(12, int(initial_size))
    factors = (1.0, 0.85, 0.72, 0.60, 0.50, 0.40)
    sizes = []
    for fac in factors:
        s = max(40, int(initial * fac))
        if not sizes or sizes[-1] != s:
            sizes.append(s)
    if sizes[-1] > 40:
        sizes.append(40)

    integrals = None
    if smart:
        try:
            integrals = _build_integrals(_render_frame(anim, ANALYZE_SIZE))
        except Exception:
            logger.exception("smart anchor: failed to render analysis frame")
            integrals = None

    chosen = None  # (size, group, bbox, anchor_cx, anchor_cy, mean, mode)

    if smart and integrals is not None:
        for size in sizes:
            if size < _SMART_MIN_SIZE:
                # Below this size the caption looks too small to be considered
                # a "feature" placement — let the meme-caption fallback take over.
                break
            fs = FontStyle(font, size)
            group = fs.render(text)
            bbox = group.bounding_box()
            tw = bbox.x2 - bbox.x1
            th = bbox.y2 - bbox.y1
            res = _best_position_for(integrals, tw, th, canvas=canvas_w)
            if res is not None and res[0] >= _SMART_MIN_SCORE:
                _, cx, cy, mean = res
                chosen = (size, group, bbox, cx, cy, float(mean), "smart")
                break

    if chosen is None:
        # Meme caption fallback: centred, near canvas bottom.
        anchor_cx = canvas_w / 2
        target_w = canvas_w * (0.88 if smart else float(max_width_ratio))
        # Allow finer-grained smaller sizes for the fallback so very long
        # captions still fit horizontally.
        fallback_sizes = list(sizes) + [s for s in (32, 24, 18, 14, 12) if s < sizes[-1]]
        for size in fallback_sizes:
            fs = FontStyle(font, size)
            group = fs.render(text)
            bbox = group.bounding_box()
            tw = bbox.x2 - bbox.x1
            th = bbox.y2 - bbox.y1
            if tw <= target_w and th <= canvas_h * 0.32:
                cy_text = canvas_h - th / 2 - 22 if smart else float(y_offset)
                chosen = (size, group, bbox, anchor_cx, cy_text, 0.0, "fallback")
                break
        if chosen is None:
            # Even at 12pt the text overflows. Use 12pt anyway (it'll wrap-clip).
            size = 12
            fs = FontStyle(font, size)
            group = fs.render(text)
            bbox = group.bounding_box()
            cy_text = (canvas_h - 30) if smart else float(y_offset)
            chosen = (size, group, bbox, anchor_cx, cy_text, 0.0, "fallback")

    size, group, bbox, anchor_cx, anchor_cy, mean, mode = chosen

    if smart and auto_color and mode == "smart" and mean > 0.55:
        fill_hex, stroke_hex = stroke_hex, fill_hex

    # Centre the text on the anchor
    cx = (bbox.x1 + bbox.x2) / 2
    cy = (bbox.y1 + bbox.y2) / 2

    layer = ShapeLayer()
    layer.name = "nftgift_caption"
    layer.shapes.append(group)
    stroke_w = max(3, size // 10)
    sr, sg, sb = _hex_to_rgb(stroke_hex)
    layer.shapes.append(Stroke(Color(sr, sg, sb), stroke_w))
    fr, fg, fb = _hex_to_rgb(fill_hex)
    layer.shapes.append(Fill(Color(fr, fg, fb)))
    layer.transform.position.value = [anchor_cx - cx, anchor_cy - cy]
    layer.in_point = anim.in_point
    layer.out_point = anim.out_point
    anim.layers.insert(0, layer)

    out = io.BytesIO()
    export_tgs(anim, out, sanitize=False, validate=False)
    data = out.getvalue()
    # Sanity: must round-trip back to valid Lottie JSON.
    json.loads(gzip.decompress(data))
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Module
# ─────────────────────────────────────────────────────────────────────────────


@loader.tds
class NFTGiftMod(loader.Module):
    """Накладывает свой текст на Lottie-анимацию NFT-подарка Telegram и складывает результат в личный стикерпак."""

    strings = {
        "name": "NFTGift",
        "no_args": (
            "ℹ️ <b>Использование</b>\n"
            "<code>{prefix}nftgift &lt;ссылка&gt; | &lt;текст&gt;</code>\n"
            "<code>{prefix}nftgift &lt;ссылка&gt; | &lt;текст&gt; | 🥳</code>  "
            "— задать свой эмодзи (по умолчанию 🎁)\n\n"
            "<i>Пример:</i> <code>{prefix}nftgift t.me/nft/PlushPepe-100 | Привет!</code>\n\n"
            "Меню настроек: <code>{prefix}nftgift settings</code>\n"
            "Также можно править параметры через <code>{prefix}config NFTGift</code>."
        ),
        "bad_link": (
            "❌ <b>Не удалось распознать ссылку.</b>\n"
            "Жду ссылку вида <code>t.me/nft/PlushPepe-100</code>"
        ),
        "fetching": "⏳ <b>Скачиваю подарок…</b>",
        "no_anim": "❌ <b>Не нашёл Lottie-анимацию для этого подарка.</b>",
        "rendering": "✏️ <b>Накладываю текст…</b>",
        "packing": "📦 <b>Добавляю в стикерпак…</b>",
        "done_with_pack": (
            "✅ <b>Готово.</b> Стикер добавлен в пак "
            "<a href=\"https://t.me/addstickers/{short_name}\">{title}</a>."
        ),
        "done_no_pack": "✅ <b>Готово.</b>",
        "pack_error": (
            "⚠️ <b>Стикер отправлен, но не получилось добавить в пак:</b> "
            "<code>{err}</code>"
        ),
        "too_big": (
            "❌ <b>Файл получился больше 64 KB ({size} KB).</b>\n"
            "Telegram такое не примет. Попробуй короче текст или уменьши шрифт в конфиге."
        ),
        "render_error": "❌ <b>Ошибка рендера:</b> <code>{err}</code>",
        "fetch_error": "❌ <b>Ошибка загрузки:</b> <code>{err}</code>",
        "lib_missing": (
            "❌ <b>Не установлены библиотеки <code>{libs}</code>.</b>\n"
            "Перезапусти юзербот — Hikka подтянет их по <code># requires</code>, либо установи вручную:\n"
            "<code>pip install lottie fonttools cairosvg Pillow numpy</code>"
        ),
        "menu_title": (
            "🎁 <b>NFTGift — настройки</b>\n\n"
            "Команда: <code>{prefix}nftgift &lt;ссылка&gt; | &lt;текст&gt; [| эмодзи]</code>\n\n"
            "<b>Текущие параметры:</b>\n"
            "• Умное размещение: <b>{smart}</b>\n"
            "• Авто-цвет текста: <b>{auto_color}</b>\n"
            "• Добавлять в пак: <b>{add_to_pack}</b>\n"
            "• Эмодзи по умолчанию: <b>{default_emoji}</b>\n"
            "• Название пака: <code>{pack_title}</code>\n"
            "• Шрифт: <code>{font}</code>\n"
            "• Кегль: <b>{font_size}</b>\n"
            "• Заливка / обводка: <code>#{fill}</code> / <code>#{stroke}</code>\n\n"
            "Подробные параметры — через <code>{prefix}config NFTGift</code>."
        ),
        "menu_unavailable": (
            "ℹ️ <b>Инлайн-меню недоступно</b> (вероятно, в Hikka не настроен инлайн-бот). "
            "Все параметры можно править через <code>{prefix}config NFTGift</code>:\n\n{body}"
        ),
        "set_ok": "✅ Сохранено.",
    }

    strings_ru = {
        "_cls_doc": "Накладывает свой текст на Lottie-анимацию NFT-подарка Telegram и складывает результат в личный стикерпак.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "smart",
                True,
                lambda: "Умное размещение: модуль сам ищет лучшее место для текста на каждом подарке",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "auto_color",
                True,
                lambda: "Если включено и фон светлый — автоматически меняет цвета заливки/обводки местами",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "add_to_pack",
                True,
                lambda: "Добавлять каждый сгенерированный стикер в твой личный NFT-Gift пак",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "default_emoji",
                "🎁",
                lambda: "Эмодзи по умолчанию для стикера, если не задан в команде",
                validator=loader.validators.String(min_len=1, max_len=8),
            ),
            loader.ConfigValue(
                "pack_title",
                "NFT Gift Stickers",
                lambda: "Название твоего стикерпака (показывается при добавлении)",
                validator=loader.validators.String(min_len=1, max_len=64),
            ),
            loader.ConfigValue(
                "font",
                "sans:weight=bold",
                lambda: "Шрифт (fontconfig-запрос, например 'DejaVu Sans:weight=bold')",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "font_size",
                140,
                lambda: "Стартовый кегль (модуль сам подберёт меньше при необходимости)",
                validator=loader.validators.Integer(minimum=12, maximum=400),
            ),
            loader.ConfigValue(
                "fill",
                "ffffff",
                lambda: "Цвет заливки текста (HEX без #)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "stroke",
                "000000",
                lambda: "Цвет обводки текста (HEX без #)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "y_offset",
                465,
                lambda: f"Запасная Y-координата текста, если умное размещение выключено (0..{CANVAS})",
                validator=loader.validators.Integer(minimum=0, maximum=CANVAS),
            ),
            loader.ConfigValue(
                "max_width_ratio",
                "0.85",
                lambda: "Доля ширины холста для текста при выключенном умном размещении (0..1)",
                validator=loader.validators.String(),
            ),
        )

    async def client_ready(self, client, db):
        self.client = client
        self.db = db

    # ── Networking ────────────────────────────────────────────────────────

    async def _fetch_tgs(self, slug: str) -> bytes:
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(f"https://t.me/nft/{slug}") as resp:
                resp.raise_for_status()
                html = await resp.text()
            m = TGS_URL_RE.search(html)
            if not m:
                return b""
            async with session.get(m.group(1)) as resp:
                resp.raise_for_status()
                return await resp.read()

    # ── Settings ──────────────────────────────────────────────────────────

    def _prefix(self) -> str:
        for attr in ("get_prefix", "prefix"):
            obj = getattr(self, attr, None)
            if callable(obj):
                try:
                    return obj()
                except Exception:
                    pass
            elif isinstance(obj, str):
                return obj
        return "."

    def _menu_text(self) -> str:
        return self.strings["menu_title"].format(
            prefix=self._prefix(),
            smart="вкл" if self.config["smart"] else "выкл",
            auto_color="вкл" if self.config["auto_color"] else "выкл",
            add_to_pack="вкл" if self.config["add_to_pack"] else "выкл",
            default_emoji=self.config["default_emoji"],
            pack_title=utils.escape_html(str(self.config["pack_title"])),
            font=utils.escape_html(str(self.config["font"])),
            font_size=self.config["font_size"],
            fill=self.config["fill"],
            stroke=self.config["stroke"],
        )

    def _menu_markup(self):
        smart = self.config["smart"]
        auto = self.config["auto_color"]
        pack = self.config["add_to_pack"]
        return [
            [
                {
                    "text": f"🧠 Умное: {'вкл' if smart else 'выкл'}",
                    "callback": self._cb_toggle,
                    "args": ("smart",),
                },
                {
                    "text": f"🎨 Авто-цвет: {'вкл' if auto else 'выкл'}",
                    "callback": self._cb_toggle,
                    "args": ("auto_color",),
                },
            ],
            [
                {
                    "text": f"📦 Пак: {'вкл' if pack else 'выкл'}",
                    "callback": self._cb_toggle,
                    "args": ("add_to_pack",),
                },
            ],
            [{"text": "🚪 Закрыть", "action": "close"}],
        ]

    async def _cb_toggle(self, call, key):
        self.config[key] = not bool(self.config[key])
        try:
            await call.edit(text=self._menu_text(), reply_markup=self._menu_markup())
        except Exception:
            logger.exception("nftgift: failed to edit menu after toggle")
            await call.answer(self.strings["set_ok"], show_alert=False)

    async def _send_settings(self, message: Message):
        # Try the inline menu first; if anything goes wrong (no inline bot,
        # aiogram error, network glitch), fall back to plain text so the user
        # can always see and edit settings via .config NFTGift.
        try:
            inline = getattr(self, "inline", None)
            if inline is not None and hasattr(inline, "form"):
                result = await inline.form(
                    text=self._menu_text(),
                    message=message,
                    reply_markup=self._menu_markup(),
                )
                if result:
                    return
        except Exception:
            logger.exception("nftgift: inline form failed, falling back to text")
        await utils.answer(
            message,
            self.strings["menu_unavailable"].format(
                prefix=self._prefix(),
                body=self._menu_text(),
            ),
        )

    # ── Sticker-pack management ───────────────────────────────────────────

    async def _ensure_pack(self, tgs_data: bytes, emoji: str):
        """
        Upload `tgs_data` as a sticker, then add it to the user's NFT-Gift
        pack — creating the pack if it doesn't exist yet. Returns
        ``(short_name, title, was_created)``.
        """
        me = await self.client.get_me()
        short_name = f"nftgift_{me.id}_pack"
        title = str(self.config["pack_title"]) or "NFT Gift Stickers"

        # Step 1 — upload the .tgs as a Telegram document.
        bio = io.BytesIO(tgs_data)
        bio.name = "nftgift.tgs"
        uploaded = await self.client.upload_file(file=bio, file_name="nftgift.tgs")
        media = await self.client(
            UploadMediaRequest(
                peer=InputPeerSelf(),
                media=InputMediaUploadedDocument(
                    file=uploaded,
                    mime_type="application/x-tgsticker",
                    attributes=[DocumentAttributeFilename("nftgift.tgs")],
                ),
            )
        )
        doc = media.document
        input_doc = InputDocument(
            id=doc.id,
            access_hash=doc.access_hash,
            file_reference=doc.file_reference,
        )
        item = InputStickerSetItem(document=input_doc, emoji=emoji)

        # Step 2 — try to add to existing pack; if it doesn't exist, create.
        try:
            await self.client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name),
                    hash=0,
                )
            )
        except StickersetInvalidError:
            await self.client(
                CreateStickerSetRequest(
                    user_id=InputUserSelf(),
                    title=title,
                    short_name=short_name,
                    stickers=[item],
                )
            )
            return short_name, title, True
        except ShortnameOccupyFailedError:
            # Race: someone else just took the short name. Pick a fallback.
            short_name = f"nftgift_{me.id}_{int(asyncio.get_event_loop().time())}_pack"
            await self.client(
                CreateStickerSetRequest(
                    user_id=InputUserSelf(),
                    title=title,
                    short_name=short_name,
                    stickers=[item],
                )
            )
            return short_name, title, True

        await self.client(
            AddStickerToSetRequest(
                stickerset=InputStickerSetShortName(short_name),
                sticker=item,
            )
        )
        return short_name, title, False

    # ── Command ───────────────────────────────────────────────────────────

    @loader.command(
        ru_doc=(
            "<ссылка> | <текст> [| эмодзи] — Наложить текст на Lottie NFT-подарка, "
            "отправить стикером и добавить в твой пак. Без аргументов — меню настроек."
        ),
    )
    async def nftgift(self, message: Message):
        """<link> | <text> [| emoji] — Overlay text on an NFT gift Lottie animation,
        send it as a sticker, and add it to the user's personal pack.
        No args → settings."""
        args = utils.get_args_raw(message) or ""

        # Settings/help should work even if heavy libs aren't installed yet.
        if not args.strip() or args.strip().lower() in ("settings", "config", "menu", "set"):
            await self._send_settings(message)
            return

        try:
            from lottie.parsers.tgs import parse_tgs  # noqa: F401
            from PIL import Image  # noqa: F401
            import numpy  # noqa: F401
        except ImportError as e:
            await utils.answer(message, self.strings["lib_missing"].format(libs=str(e)))
            return

        if "|" not in args:
            await utils.answer(message, self.strings["no_args"].format(prefix=self._prefix()))
            return

        parts = [p.strip() for p in args.split("|")]
        link_part = parts[0]
        text = parts[1] if len(parts) > 1 else ""
        emoji = parts[2] if len(parts) > 2 and parts[2] else str(self.config["default_emoji"])

        slug = _parse_link(link_part)
        if not slug or not text:
            await utils.answer(message, self.strings["bad_link"])
            return

        await utils.answer(message, self.strings["fetching"])
        try:
            tgs = await self._fetch_tgs(slug)
        except Exception as exc:
            logger.exception("nftgift: failed to fetch")
            await utils.answer(message, self.strings["fetch_error"].format(err=utils.escape_html(str(exc))))
            return

        if not tgs:
            await utils.answer(message, self.strings["no_anim"])
            return

        await utils.answer(message, self.strings["rendering"])
        try:
            data = await asyncio.to_thread(
                _render_caption,
                tgs,
                text,
                font=str(self.config["font"]),
                initial_size=int(self.config["font_size"]),
                fill_hex=str(self.config["fill"]),
                stroke_hex=str(self.config["stroke"]),
                y_offset=int(self.config["y_offset"]),
                max_width_ratio=float(self.config["max_width_ratio"]),
                smart=bool(self.config["smart"]),
                auto_color=bool(self.config["auto_color"]),
            )
        except Exception as exc:
            logger.exception("nftgift: render failed")
            await utils.answer(message, self.strings["render_error"].format(err=utils.escape_html(str(exc))))
            return

        if len(data) > MAX_TGS_SIZE:
            await utils.answer(
                message,
                self.strings["too_big"].format(size=len(data) // 1024),
            )
            return

        bio = io.BytesIO(data)
        bio.name = "nftgift.tgs"
        await self.client.send_file(
            message.peer_id,
            bio,
            mime_type="application/x-tgsticker",
            attributes=[DocumentAttributeFilename("nftgift.tgs")],
            reply_to=message.reply_to_msg_id,
        )

        # Try to add to the user's personal pack — but never let this break the
        # primary "send sticker" flow.
        if bool(self.config["add_to_pack"]):
            try:
                await utils.answer(message, self.strings["packing"])
                short_name, title, _ = await self._ensure_pack(data, emoji)
                await utils.answer(
                    message,
                    self.strings["done_with_pack"].format(
                        short_name=short_name,
                        title=utils.escape_html(title),
                    ),
                )
            except Exception as exc:
                logger.exception("nftgift: failed to add to pack")
                await utils.answer(
                    message,
                    self.strings["pack_error"].format(err=utils.escape_html(str(exc))),
                )
            return

        await utils.answer(message, self.strings["done_no_pack"])
