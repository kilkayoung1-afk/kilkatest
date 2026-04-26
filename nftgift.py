# meta developer: @Kilka_Young
# meta name: NFTGift
# requires: aiohttp lottie fonttools

"""
NFT Gift caption module for Hikka userbot.

Скачивает Lottie-анимацию NFT-подарка Telegram (например, t.me/nft/PlushPepe-100),
накладывает поверх неё текстовый слой, упаковывает обратно в .tgs и отправляет
анимированным стикером.
"""

import asyncio
import gzip
import io
import json
import logging
import re

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


def _render_caption(
    tgs_bytes: bytes,
    text: str,
    font: str,
    initial_size: int,
    fill_hex: str,
    stroke_hex: str,
    y: int,
    max_width_ratio: float,
) -> bytes:
    """Decompress .tgs, add a centred text layer, recompress."""
    from lottie.exporters import export_tgs
    from lottie.objects import Color, Fill, ShapeLayer, Stroke
    from lottie.parsers.tgs import parse_tgs
    from lottie.utils.font import FontStyle

    anim = parse_tgs(io.BytesIO(tgs_bytes))

    target_width = anim.width * max_width_ratio
    size = max(12, int(initial_size))
    group = None
    bbox = None
    while True:
        fs = FontStyle(font, size)
        group = fs.render(text)
        bbox = group.bounding_box()
        width = bbox.x2 - bbox.x1
        if width <= target_width or size <= 12:
            break
        size = max(12, int(size * target_width / width * 0.95))

    cx = (bbox.x1 + bbox.x2) / 2

    layer = ShapeLayer()
    layer.name = "nftgift_caption"
    layer.shapes.append(group)
    stroke_w = max(2, size // 12)
    sr, sg, sb = _hex_to_rgb(stroke_hex)
    layer.shapes.append(Stroke(Color(sr, sg, sb), stroke_w))
    fr, fg, fb = _hex_to_rgb(fill_hex)
    layer.shapes.append(Fill(Color(fr, fg, fb)))
    layer.transform.position.value = [anim.width / 2 - cx, int(y)]
    layer.in_point = anim.in_point
    layer.out_point = anim.out_point
    anim.layers.insert(0, layer)

    out = io.BytesIO()
    export_tgs(anim, out, sanitize=False, validate=False)
    data = out.getvalue()
    # Validate that we still have a valid Lottie JSON inside the gzip.
    json.loads(gzip.decompress(data))
    return data


@loader.tds
class NFTGiftMod(loader.Module):
    """Накладывает свой текст на Lottie-анимацию NFT-подарка Telegram. By @Kilka_Young"""

    strings = {
        "name": "NFTGift",
        "no_args": (
            "❌ <b>Использование:</b>\n"
            "<code>{prefix}nftgift &lt;ссылка&gt; | &lt;текст&gt;</code>\n\n"
            "<i>Пример:</i> <code>{prefix}nftgift t.me/nft/PlushPepe-100 | Привет!</code>"
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
            "❌ <b>Не установлены библиотеки <code>lottie</code> / <code>fonttools</code>.</b>\n"
            "Перезапусти юзербот — Hikka подтянет их по <code># requires</code>, либо установи вручную:\n"
            "<code>pip install lottie fonttools</code>"
        ),
    }

    strings_ru = {
        "_cls_doc": "Накладывает свой текст на Lottie-анимацию NFT-подарка Telegram. By @Kilka_Young",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "font",
                "sans:weight=bold",
                lambda: "Шрифт для текста (fontconfig-запрос, например 'sans:weight=bold')",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "font_size",
                80,
                lambda: "Стартовый размер шрифта (модуль авто-уменьшит, чтобы текст влез)",
                validator=loader.validators.Integer(minimum=12, maximum=200),
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
                lambda: f"Y-координата базовой линии текста (0..{CANVAS})",
                validator=loader.validators.Integer(minimum=0, maximum=CANVAS),
            ),
            loader.ConfigValue(
                "max_width_ratio",
                "0.85",
                lambda: "Доля ширины холста, в которую должен поместиться текст (0..1)",
                validator=loader.validators.String(),
            ),
        )

    async def client_ready(self, client, db):
        self.client = client
        self.db = db

    async def _fetch_tgs(self, slug: str) -> bytes:
        """Скачивает .tgs анимацию NFT-подарка по slug."""
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

    @loader.command(
        ru_doc="<ссылка> | <текст> — Положить свой текст поверх Lottie-анимации NFT-подарка",
    )
    async def nftgift(self, message: Message):
        """<link> | <text> — Overlay your own text on an NFT gift Lottie animation"""
        try:
            from lottie.parsers.tgs import parse_tgs  # noqa: F401
        except ImportError:
            await utils.answer(message, self.strings["lib_missing"])
            return

        prefix = self.get_prefix() if hasattr(self, "get_prefix") else "."
        args = utils.get_args_raw(message)
        if not args or "|" not in args:
            await utils.answer(message, self.strings["no_args"].format(prefix=prefix))
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
                str(self.config["font"]),
                int(self.config["font_size"]),
                str(self.config["fill"]),
                str(self.config["stroke"]),
                int(self.config["y_offset"]),
                float(self.config["max_width_ratio"]),
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
