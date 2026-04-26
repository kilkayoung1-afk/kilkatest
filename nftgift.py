# meta developer: @Kilka_Young
# meta name: NFTGift
# requires: aiohttp lottie fonttools cairosvg Pillow numpy

"""
NFT Gift caption module for Hikka userbot.

Скачивает Lottie-анимацию NFT-подарка Telegram (например, t.me/nft/PlushPepe-100),
сам выбирает на анимации лучшее место для подписи (например, на сердечке у Plush Pepe),
аккуратно вписывает туда твой текст и отправляет результат анимированным стикером (.tgs).
"""

import asyncio
import gzip
import io
import json
import logging
import re
import subprocess

import aiohttp
from telethon.tl.types import DocumentAttributeFilename, Message

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


def _smart_anchor(img):
    """
    Find the best rectangular area on the rendered sticker frame to drop a
    text caption onto. Returns (cx, cy, w, h, mean_brightness) in *normalized*
    coordinates (0..1) relative to the canvas. The caller scales these to
    Lottie units (pixels in 512×512).

    Heuristic: scan rectangles of varying aspect ratios; reward (a) high alpha
    coverage (must be on the sticker, not in the transparent margin),
    (b) low pixel-brightness variance (smooth area), (c) extreme brightness
    (very dark or very light, so coloured text reads well over it),
    (d) large size.
    """
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

    ii_b = integral(brightness)
    ii_b2 = integral(brightness * brightness)
    ii_a = integral(alpha)

    best = None
    for h_frac in (0.45, 0.35, 0.28, 0.22, 0.16, 0.12):
        bh = max(8, int(h * h_frac))
        for asp in (3.5, 4.5, 6.0):
            bw = int(bh * asp)
            if bw > w or bh > h:
                continue
            for y0 in range(0, h - bh + 1, 2):
                for x0 in range(0, w - bw + 1, 2):
                    n = bh * bw
                    cov = _box_sum(ii_a, y0, x0, y0 + bh, x0 + bw) / n
                    if cov < 0.85:
                        continue
                    s = _box_sum(ii_b, y0, x0, y0 + bh, x0 + bw)
                    s2 = _box_sum(ii_b2, y0, x0, y0 + bh, x0 + bw)
                    mean = s / n
                    var = max(0.0, s2 / n - mean * mean)
                    std = var ** 0.5
                    smooth = 1.0 - min(std * 5, 1.0)
                    contrast = abs(mean - 0.5) * 2.0  # prefer near-black or near-white
                    size_term = n / (h * w)
                    score = smooth * 0.5 + contrast * 0.3 + size_term * 0.2
                    if best is None or score > best[0]:
                        best = (score, y0, x0, bh, bw, mean)

    if best is None:
        # Sticker is entirely empty. Fall back to bottom-centre.
        return (0.5, 0.91, 0.85, 0.15, 0.0)

    score, y0, x0, bh, bw, mean = best
    cx = (x0 + bw / 2) / w
    cy = (y0 + bh / 2) / h
    return (cx, cy, bw / w, bh / h, float(mean))


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

    When `smart` is True, the placement (centre, max width, max height) is
    detected from the sticker's middle frame. When False, text is centred
    horizontally and placed at `y_offset` with `max_width_ratio` of canvas.

    When `auto_color` is True (and smart is True), fill / stroke are flipped
    automatically: bright background → dark text + light halo and vice versa.
    """
    from lottie.exporters import export_tgs
    from lottie.objects import Color, Fill, ShapeLayer, Stroke
    from lottie.parsers.tgs import parse_tgs
    from lottie.utils.font import FontStyle

    anim = parse_tgs(io.BytesIO(tgs_bytes))
    canvas_w = anim.width
    canvas_h = anim.height

    if smart:
        try:
            frame_img = _render_frame(anim, ANALYZE_SIZE)
            cx_n, cy_n, bw_n, bh_n, mean = _smart_anchor(frame_img)
        except Exception:
            logger.exception("smart anchor failed, falling back to manual placement")
            cx_n, cy_n, bw_n, bh_n, mean = (0.5, y_offset / canvas_h, max_width_ratio, 0.15, 0.0)
        anchor_cx = cx_n * canvas_w
        anchor_cy = cy_n * canvas_h
        max_text_w = bw_n * canvas_w * 0.92
        max_text_h = bh_n * canvas_h * 0.85
        if auto_color and mean > 0.55:
            fill_hex, stroke_hex = stroke_hex, fill_hex  # invert
    else:
        anchor_cx = canvas_w / 2
        anchor_cy = float(y_offset)
        max_text_w = canvas_w * max_width_ratio
        max_text_h = canvas_h  # not constrained vertically in legacy mode
        mean = 0.0

    # Iteratively shrink font until text fits both width and height limits.
    size = max(12, int(initial_size))
    group = None
    bbox = None
    for _ in range(20):
        fs = FontStyle(font, size)
        group = fs.render(text)
        bbox = group.bounding_box()
        tw = bbox.x2 - bbox.x1
        th = bbox.y2 - bbox.y1
        if (tw <= max_text_w and th <= max_text_h) or size <= 12:
            break
        ratio_w = max_text_w / tw if tw > 0 else 1.0
        ratio_h = max_text_h / th if th > 0 else 1.0
        size = max(12, int(size * min(ratio_w, ratio_h) * 0.95))

    # Centre the text on the anchor
    cx = (bbox.x1 + bbox.x2) / 2
    cy = (bbox.y1 + bbox.y2) / 2

    layer = ShapeLayer()
    layer.name = "nftgift_caption"
    layer.shapes.append(group)
    stroke_w = max(2, size // 12)
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
    """Накладывает свой текст на Lottie-анимацию NFT-подарка Telegram. By @Kilka_Young"""

    strings = {
        "name": "NFTGift",
        "no_args": (
            "❌ <b>Использование:</b>\n"
            "<code>{prefix}nftgift &lt;ссылка&gt; | &lt;текст&gt;</code>\n\n"
            "<i>Пример:</i> <code>{prefix}nftgift t.me/nft/PlushPepe-100 | Привет!</code>\n\n"
            "Настройки: <code>{prefix}nftgift settings</code>"
        ),
        "bad_link": (
            "❌ <b>Не удалось распознать ссылку.</b>\n"
            "Жду ссылку вида <code>t.me/nft/PlushPepe-100</code>"
        ),
        "fetching": "⏳ <b>Скачиваю подарок…</b>",
        "no_anim": "❌ <b>Не нашёл Lottie-анимацию для этого подарка.</b>",
        "rendering": "✏️ <b>Накладываю текст…</b>",
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
            "Команда: <code>{prefix}nftgift &lt;ссылка&gt; | &lt;текст&gt;</code>\n\n"
            "<b>Текущие параметры:</b>\n"
            "• Умное размещение: <b>{smart}</b>\n"
            "• Авто-цвет текста: <b>{auto_color}</b>\n"
            "• Шрифт: <code>{font}</code>\n"
            "• Кегль (стартовый): <b>{font_size}</b>\n"
            "• Заливка / обводка: <code>#{fill}</code> / <code>#{stroke}</code>\n"
            "• Запасная Y-координата: <b>{y_offset}</b>\n"
            "• Доля ширины: <b>{ratio}</b>"
        ),
        "ask_font": "Введи fontconfig-запрос (например, <code>DejaVu Sans:weight=bold</code>):",
        "ask_size": "Введи стартовый размер шрифта (12..200):",
        "ask_fill": "Введи цвет заливки в HEX (без #):",
        "ask_stroke": "Введи цвет обводки в HEX (без #):",
        "ask_yoffset": f"Введи запасную Y-координату (0..{CANVAS}):",
        "ask_ratio": "Введи долю ширины холста для текста (например, 0.85):",
        "set_ok": "✅ Сохранено.",
        "set_bad": "❌ Не удалось распарсить значение.",
    }

    strings_ru = {
        "_cls_doc": "Накладывает свой текст на Lottie-анимацию NFT-подарка Telegram. By @Kilka_Young",
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
                "font",
                "sans:weight=bold",
                lambda: "Шрифт (fontconfig-запрос, например 'DejaVu Sans:weight=bold')",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "font_size",
                100,
                lambda: "Стартовый кегль (модуль авто-уменьшит, чтобы текст влез)",
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

    # ── Inline settings menu ──────────────────────────────────────────────

    def _menu_text(self) -> str:
        return self.strings["menu_title"].format(
            prefix=self._prefix(),
            smart="вкл" if self.config["smart"] else "выкл",
            auto_color="вкл" if self.config["auto_color"] else "выкл",
            font=self.config["font"],
            font_size=self.config["font_size"],
            fill=self.config["fill"],
            stroke=self.config["stroke"],
            y_offset=self.config["y_offset"],
            ratio=self.config["max_width_ratio"],
        )

    def _menu_markup(self):
        smart = self.config["smart"]
        auto = self.config["auto_color"]
        return [
            [
                {"text": f"🧠 Умное размещение: {'✅' if smart else '❌'}",
                 "callback": self._cb_toggle, "args": ("smart",)},
                {"text": f"🎨 Авто-цвет: {'✅' if auto else '❌'}",
                 "callback": self._cb_toggle, "args": ("auto_color",)},
            ],
            [
                {"text": "🔤 Шрифт", "input": self.strings["ask_font"],
                 "handler": self._cb_set, "args": ("font", "str")},
                {"text": "🔠 Кегль", "input": self.strings["ask_size"],
                 "handler": self._cb_set, "args": ("font_size", "int")},
            ],
            [
                {"text": "🎨 Заливка", "input": self.strings["ask_fill"],
                 "handler": self._cb_set, "args": ("fill", "hex")},
                {"text": "🖋 Обводка", "input": self.strings["ask_stroke"],
                 "handler": self._cb_set, "args": ("stroke", "hex")},
            ],
            [
                {"text": "📐 Y запасной", "input": self.strings["ask_yoffset"],
                 "handler": self._cb_set, "args": ("y_offset", "int")},
                {"text": "📏 Ширина (доля)", "input": self.strings["ask_ratio"],
                 "handler": self._cb_set, "args": ("max_width_ratio", "float_str")},
            ],
            [{"text": "🚪 Закрыть", "action": "close"}],
        ]

    async def _cb_toggle(self, call, key):
        self.config[key] = not bool(self.config[key])
        await call.edit(text=self._menu_text(), reply_markup=self._menu_markup())

    async def _cb_set(self, call, value, key, kind):
        try:
            if kind == "int":
                v = int(value.strip())
            elif kind == "hex":
                _hex_to_rgb(value)
                v = value.strip().lstrip("#").lower()
            elif kind == "float_str":
                f = float(value.strip())
                if not (0 < f <= 1):
                    raise ValueError("ratio must be in (0, 1]")
                v = str(f)
            else:
                v = value.strip()
            self.config[key] = v
            await call.answer(self.strings["set_ok"], show_alert=False)
        except Exception:
            await call.answer(self.strings["set_bad"], show_alert=True)
            return
        await call.edit(text=self._menu_text(), reply_markup=self._menu_markup())

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

    # ── Commands ──────────────────────────────────────────────────────────

    async def _send_settings(self, message: Message):
        await self.inline.form(
            text=self._menu_text(),
            message=message,
            reply_markup=self._menu_markup(),
        )

    @loader.command(
        ru_doc=(
            "<ссылка> | <текст> — Положить свой текст поверх Lottie-анимации NFT-подарка. "
            "Без аргументов — открыть меню настроек."
        ),
    )
    async def nftgift(self, message: Message):
        """<link> | <text> — Overlay text on an NFT gift Lottie animation. No args → settings menu."""
        try:
            from lottie.parsers.tgs import parse_tgs  # noqa: F401
            from PIL import Image  # noqa: F401
            import numpy  # noqa: F401
        except ImportError as e:
            await utils.answer(message, self.strings["lib_missing"].format(libs=str(e)))
            return

        args = utils.get_args_raw(message) or ""
        if not args.strip() or args.strip().lower() in ("settings", "config", "menu", "set"):
            await self._send_settings(message)
            return

        if "|" not in args:
            await utils.answer(message, self.strings["no_args"].format(prefix=self._prefix()))
            return

        link_part, text = (s.strip() for s in args.split("|", 1))
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
        if message.out:
            try:
                await message.delete()
            except Exception:
                pass
