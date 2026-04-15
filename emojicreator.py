# =================== PigAIStickers.py ===================
# meta developer: @Kilka_Young
# scope: hikka_only
# scope: hikka_min 1.6.3
# requires: Pillow
# channel: @mypigAI

import asyncio
import io
import json
import os
import re
import gzip
from typing import Dict, List, Any, Optional

from PIL import Image

from telethon.tl import functions, types
from telethon.tl.types import (
    DocumentAttributeSticker,
    DocumentAttributeCustomEmoji,
    InputStickerSetShortName,
    InputStickerSetID,
    InputStickerSetEmpty,
    Message,
    MessageEntityCustomEmoji,
)

from .. import loader, utils

# Кастомные ID для премиум-эмодзи (интерфейс)
PE = {
    "ok": "5870633910337015697",
    "err": "5870657884844462243",
    "sticker": "5886285355279193209",
    "pack": "5778672437122045013",
    "link": "5769289093221454192",
    "stats": "5870921681735781843",
    "clock": "5983150113483134607",
    "write": "5870753782874246579",
}

# Канал и владелец для брендирования паков
CHANNEL_USERNAME = "mypigAI"
OWNER_USERNAME = "Kilka_Young"

def pe(emoji: str, eid: str) -> str:
    return f'<emoji id="{eid}">{emoji}</emoji>'

def validate_short_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]{1,64}", name))

async def upload_sticker_item(client, me_entity, uploaded_file, mime: str, emoji_str: str, is_emoji_pack: bool):
    """Загружает файл стикера/эмодзи и подготавливает его для добавления в пак."""
    if is_emoji_pack:
        sticker_attr = types.DocumentAttributeCustomEmoji(
            alt=emoji_str,
            stickerset=types.InputStickerSetEmpty(),
            free=False,
            text_color=False,
        )
    else:
        sticker_attr = types.DocumentAttributeSticker(
            alt=emoji_str,
            stickerset=types.InputStickerSetEmpty(),
        )
    if mime == "application/x-tgsticker":
        media = types.InputMediaUploadedDocument(
            file=uploaded_file,
            mime_type="application/x-tgsticker",
            attributes=[types.DocumentAttributeFilename(file_name="sticker.tgs"), sticker_attr],
        )
    else:
        media = types.InputMediaUploadedDocument(
            file=uploaded_file,
            mime_type="image/webp",
            attributes=[types.DocumentAttributeFilename(file_name="sticker.webp"), sticker_attr],
        )
    result = await client(functions.messages.UploadMediaRequest(peer=me_entity, media=media))
    real_doc = result.document
    return types.InputStickerSetItem(
        document=types.InputDocument(
            id=real_doc.id,
            access_hash=real_doc.access_hash,
            file_reference=real_doc.file_reference,
        ),
        emoji=emoji_str,
    )

@loader.tds
class PigAIStickersMod(loader.Module):
    """Создание эмодзи-паков и стикеров для @mypigAI"""

    strings = {"name": "PigAIStickers"}

    def __init__(self):
        self._sessions: Dict[int, Dict[str, Any]] = {}

    @loader.command()
    async def apig(self, message: Message):
        """<reply to premium emoji> - Создать эмодзи-пак из одного премиум-эмодзи."""
        reply = await message.get_reply_message()
        if not reply:
            await utils.answer(message, pe("❌", PE["err"]) + " Ответьте на сообщение с премиум-эмодзи.")
            return

        target_doc = None
        target_set_id = None
        is_emoji = False

        if reply.sticker:
            doc = reply.sticker
            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeSticker):
                    ss = attr.stickerset
                    if isinstance(ss, (InputStickerSetShortName, InputStickerSetID)):
                        target_doc, target_set_id = doc, ss
                        is_emoji = False
                        break
        if not target_doc:
            for ent in (reply.entities or []):
                if isinstance(ent, MessageEntityCustomEmoji):
                    emoji_docs = await self._client(
                        functions.messages.GetCustomEmojiDocumentsRequest(document_id=[ent.document_id])
                    )
                    if not emoji_docs:
                        continue
                    doc = emoji_docs[0]
                    for attr in doc.attributes:
                        if isinstance(attr, (DocumentAttributeCustomEmoji, DocumentAttributeSticker)):
                            ss = getattr(attr, "stickerset", None)
                            if ss and not isinstance(ss, InputStickerSetEmpty):
                                target_doc, target_set_id = doc, ss
                                is_emoji = True
                                break
                    if target_doc:
                        break

        if not target_doc:
            await utils.answer(message, pe("❌", PE["err"]) + " Не удалось найти подходящий стикер или эмодзи.")
            return

        uid = message.sender_id
        self._sessions[uid] = {
            "type": "emoji" if is_emoji else "sticker",
            "doc": target_doc,
            "set_id": target_set_id,
            "step": "name",
        }

        await message.delete()
        await self.inline.form(
            text=self._step_text(uid),
            reply_markup=self._step_markup(uid),
            message=message
        )

    @loader.command()
    async def apigpack(self, message: Message):
        """<reply to a sticker/emoji pack> - Создать пак из 90 эмодзи/стикеров."""
        reply = await message.get_reply_message()
        if not reply:
            await utils.answer(message, pe("❌", PE["err"]) + " Ответьте на стикер или премиум эмодзи из целевого пака.")
            return

        target_set_id = None
        is_emoji = False
        if reply.sticker:
            doc = reply.sticker
            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeSticker):
                    ss = attr.stickerset
                    if isinstance(ss, (InputStickerSetShortName, InputStickerSetID)):
                        target_set_id = ss
                        is_emoji = False
                        break
        if not target_set_id:
            for ent in (reply.entities or []):
                if isinstance(ent, MessageEntityCustomEmoji):
                    emoji_docs = await self._client(
                        functions.messages.GetCustomEmojiDocumentsRequest(document_id=[ent.document_id])
                    )
                    if not emoji_docs:
                        continue
                    doc = emoji_docs[0]
                    for attr in doc.attributes:
                        if isinstance(attr, (DocumentAttributeCustomEmoji, DocumentAttributeSticker)):
                            ss = getattr(attr, "stickerset", None)
                            if ss and not isinstance(ss, InputStickerSetEmpty):
                                target_set_id = ss
                                is_emoji = True
                                break
                    if target_set_id:
                        break

        if not target_set_id:
            await utils.answer(message, pe("❌", PE["err"]) + " Не удалось определить исходный пак.")
            return

        try:
            full_set = await self._client(functions.messages.GetStickerSetRequest(
                stickerset=target_set_id,
                hash=0
            ))
        except Exception as e:
            await utils.answer(message, pe("❌", PE["err"]) + f" Не удалось загрузить пак: {e}")
            return

        uid = message.sender_id
        self._sessions[uid] = {
            "type": "emoji" if is_emoji else "sticker",
            "full_set": full_set,
            "set_id": target_set_id,
            "step": "name",
        }

        await message.delete()
        await self.inline.form(
            text=self._step_text(uid, pack=True),
            reply_markup=self._step_markup(uid, pack=True),
            message=message
        )

    def _step_text(self, uid: int, pack: bool = False) -> str:
        s = self._sessions[uid]
        if pack:
            return (
                pe("🖌", PE["sticker"]) + " <b>Создание пака из 90 штук</b>\n\n"
                f"Исходный пак: <b>{s['full_set'].set.title}</b>\n"
                f"Тип: <b>{'Эмодзи' if s['type'] == 'emoji' else 'Стикеры'}</b>\n"
                "Введите короткое имя для нового пака (a-z, 0-9, _)."
            )
        else:
            return (
                pe("🖌", PE["sticker"]) + " <b>Создание эмодзи-пака</b>\n\n"
                "Будет создан пак с одним эмодзи/стикером.\n"
                "Введите короткое имя для нового пака (a-z, 0-9, _)."
            )

    def _step_markup(self, uid: int, pack: bool = False):
        return [[
            {
                "text": "Ввести название пака",
                "icon_custom_emoji_id": PE["write"],
                "input": "Введите short_name пака (a-z, 0-9, _)",
                "handler": self._input_name_pack if pack else self._input_name,
                "args": (uid,),
            }
        ]]

    async def _input_name(self, call, value: str, uid: int):
        s = self._sessions.get(uid)
        if not s:
            await call.answer("Сессия устарела.", show_alert=True)
            return
        clean = value.strip().lower()
        if not validate_short_name(clean):
            await call.answer("Только a-z, 0-9, _ (1-64 символа).", show_alert=True)
            return

        s["pack_name"] = f"{clean}_by_{OWNER_USERNAME}"
        s["step"] = "processing"
        await call.edit(text=pe("⏰", PE["clock"]) + " <b>Создаём пак...</b>")
        asyncio.ensure_future(self._do_create_single(call, uid))

    async def _input_name_pack(self, call, value: str, uid: int):
        s = self._sessions.get(uid)
        if not s:
            await call.answer("Сессия устарела.", show_alert=True)
            return
        clean = value.strip().lower()
        if not validate_short_name(clean):
            await call.answer("Только a-z, 0-9, _ (1-64 символа).", show_alert=True)
            return

        s["pack_name"] = f"{clean}_by_{OWNER_USERNAME}"
        s["step"] = "processing"
        await call.edit(text=pe("⏰", PE["clock"]) + " <b>Создаём пак из 90 штук...</b>")
        asyncio.ensure_future(self._do_create_pack(call, uid))

    async def _do_create_single(self, call, uid: int):
        s = self._sessions[uid]
        doc = s["doc"]
        pack_name = s["pack_name"]
        pack_type = s["type"]

        me = await self._client.get_me()
        me_entity = await self._client.get_input_entity("me")

        try:
            raw = await self._client.download_media(doc, bytes)
            mime = getattr(doc, "mime_type", "")
            if mime == "application/x-tgsticker":
                buf = io.BytesIO(raw)
                buf.name = "sticker.tgs"
            else:
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
                img = img.resize((512, 512), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="WEBP", lossless=True)
                buf.seek(0)
                buf.name = "sticker.webp"

            emoji_str = "🐷"
            for attr in doc.attributes:
                if isinstance(attr, (DocumentAttributeCustomEmoji, DocumentAttributeSticker)):
                    emoji_str = getattr(attr, "alt", None) or "🐷"
                    break

            uploaded = await self._client.upload_file(buf, file_name=buf.name)
            item = await upload_sticker_item(
                self._client, me_entity, uploaded, mime, emoji_str, pack_type == "emoji"
            )

            is_emojis = (pack_type == "emoji")
            await self._client(functions.stickers.CreateStickerSetRequest(
                user_id=me.id,
                title=f"{emoji_str} Pack by {CHANNEL_USERNAME}",
                short_name=pack_name,
                stickers=[item],
                emojis=is_emojis,
            ))

            pack_link = f"https://t.me/{'addemoji/' if is_emojis else 'addstickers/'}{pack_name}"
        except Exception as e:
            await call.edit(text=pe("❌", PE["err"]) + f" <b>Ошибка:</b>\n<code>{e}</code>")
            self._sessions.pop(uid, None)
            return

        self._save_stats(pack_name, pack_link, 1, pack_type)
        await call.edit(
            text=(
                pe("✅", PE["ok"]) + " <b>Готово!</b>\n\n"
                f"{pe('🐷', PE['sticker'])} Пак создан: <code>{pack_name}</code>\n"
                f"{pe('🔗', PE['link'])} <a href='{pack_link}'>{pack_link}</a>"
            ),
            reply_markup=[[{"text": "Открыть пак", "icon_custom_emoji_id": PE["link"], "url": pack_link}]],
        )
        self._sessions.pop(uid, None)

    async def _do_create_pack(self, call, uid: int):
        s = self._sessions[uid]
        full_set = s["full_set"]
        pack_name = s["pack_name"]
        pack_type = s["type"]

        docs = list(full_set.documents)
        if len(docs) > 90:
            docs = docs[:90]
        elif len(docs) < 90:
            docs = docs * (90 // len(docs)) + docs[:90 % len(docs)]

        total = len(docs)
        me = await self._client.get_me()
        me_entity = await self._client.get_input_entity("me")
        input_stickers = []

        for i, doc in enumerate(docs):
            try:
                raw = await self._client.download_media(doc, bytes)
                mime = getattr(doc, "mime_type", "")
                if mime == "application/x-tgsticker":
                    buf = io.BytesIO(raw)
                    buf.name = "sticker.tgs"
                else:
                    img = Image.open(io.BytesIO(raw)).convert("RGBA")
                    img = img.resize((512, 512), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="WEBP", lossless=True)
                    buf.seek(0)
                    buf.name = "sticker.webp"

                emoji_str = "🐷"
                for attr in doc.attributes:
                    if isinstance(attr, (DocumentAttributeCustomEmoji, DocumentAttributeSticker)):
                        emoji_str = getattr(attr, "alt", None) or "🐷"
                        break

                uploaded = await self._client.upload_file(buf, file_name=buf.name)
                item = await upload_sticker_item(
                    self._client, me_entity, uploaded, mime, emoji_str, pack_type == "emoji"
                )
                input_stickers.append(item)

                if total > 1:
                    bar = "█" * (i + 1) + "░" * (total - i - 1)
                    pct = int((i + 1) / total * 100)
                    await call.edit(
                        text=(
                            pe("⏰", PE["clock"]) + " <b>Создаём пак из 90 штук...</b>\n\n"
                            f"<code>[{bar}]</code> {pct}%\n"
                            f"Обработано: <b>{i + 1}/{total}</b>"
                        )
                    )
            except Exception:
                pass
            await asyncio.sleep(0.05)

        if not input_stickers:
            await call.edit(text=pe("❌", PE["err"]) + " Не удалось обработать ни одного стикера.")
            self._sessions.pop(uid, None)
            return

        try:
            is_emojis = (pack_type == "emoji")
            await self._client(functions.stickers.CreateStickerSetRequest(
                user_id=me.id,
                title=f"90 Pack by {CHANNEL_USERNAME}",
                short_name=pack_name,
                stickers=input_stickers,
                emojis=is_emojis,
            ))
            pack_link = f"https://t.me/{'addemoji/' if is_emojis else 'addstickers/'}{pack_name}"
        except Exception as e:
            await call.edit(text=pe("❌", PE["err"]) + f" Ошибка создания пака: <code>{e}</code>")
            self._sessions.pop(uid, None)
            return

        self._save_stats(pack_name, pack_link, total, pack_type)
        await call.edit(
            text=(
                pe("✅", PE["ok"]) + " <b>Готово!</b>\n\n"
                f"{pe('🐷', PE['sticker'])} Пак создан: <code>{pack_name}</code>\n"
                f"{pe('📦', PE['pack'])} Эмодзи/стикеров: <b>{total}</b> шт.\n\n"
                f"{pe('🔗', PE['link'])} <a href='{pack_link}'>{pack_link}</a>"
            ),
            reply_markup=[[{"text": "Открыть пак", "icon_custom_emoji_id": PE["link"], "url": pack_link}]],
        )
        self._sessions.pop(uid, None)

    def _save_stats(self, name, link, count, ptype):
        stats = self.db.get("PigAIStickers", "stats", [])
        stats.append({
            "name": name,
            "link": link,
            "count": count,
            "type": ptype,
        })
        self.db.set("PigAIStickers", "stats", stats)

    @loader.command()
    async def apigstats(self, message: Message):
        """Показать статистику созданных паков."""
        stats = self.db.get("PigAIStickers", "stats", [])
        if not stats:
            await utils.answer(message, pe("📊", PE["stats"]) + " Ещё ни одного пака не создано.")
            return

        lines = [
            pe("📊", PE["stats"]) + " <b>Статистика PigAIStickers</b>\n"
            f"Всего паков: <b>{len(stats)}</b>\n"
        ]
        for i, entry in enumerate(reversed(stats[-20:]), 1):
            t_label = "🎨 Эмодзи-пак" if entry.get("type") == "emoji" else "🖼 Стикерпак"
            lines.append(
                f"\n<b>{i}.</b> {t_label} <code>{entry['name']}</code>\n"
                f"   {pe('📦', PE['pack'])} <b>{entry['count']}</b> шт.\n"
                f"   {pe('🔗', PE['link'])} <a href='{entry['link']}'>{entry['link']}</a>"
            )
        await utils.answer(message, "\n".join(lines), parse_mode="HTML")
