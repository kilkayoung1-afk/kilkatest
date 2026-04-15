# █▀▄▀█ █▀▀ ▀█▀ ▄▀█   █▀▄ █▀▀ █░█ █▀▀ █░░ █▀█ █▀█ █▀▀ █▀█
# █░▀░█ ██▄ ░█░ █▀█   █▄▀ ██▄ ▀▄▀ ██▄ █▄▄ █▄█ █▀▀ ██▄ █▀▄
# meta developer: @Kilka_Young
# meta name: TempMail
# requires: aiohttp

import logging
import asyncio
import aiohttp
import random
import string
import time
import re
from telethon.tl.types import Message
from .. import loader, utils

logger = logging.getLogger(__name__)

MAIL_API = "https://api.mail.tm"
EMAIL_LIFETIME = 10 * 60

@loader.tds
class TempMailMod(loader.Module):
    """Модуль для создания временных почт (mail.tm). Поддерживает просмотр ящика по команде."""
    
    strings = {
        "name": "TempMail",
        "email_created": "<b>✅ Временная почта создана!</b>\n\n📧 <b>Адрес:</b> <code>{}</code>\n⏳ <b>Действует до:</b> <code>{}</code>\n\n<i>Письма будут приходить сюда автоматически.</i>",
        "wait_cooldown": "<b>⏳ Подождите, создавать почту можно не чаще раза в 30 секунд.</b>",
        "added_user": "<b>✅ Пользователь <code>{}</code> добавлен в список доверенных.</b>",
        "removed_user": "<b>❌ Пользователь <code>{}</code> удален из списка доверенных.</b>",
        "no_email": "<b>❌ Активная почта не найдена.</b>",
        "inbox_empty": "<b>📭 В почтовом ящике пока пусто.</b>",
        "inbox_list": "<b>📂 Список сообщений ({}):</b>\n\n{}",
        "new_mail": "<b>📨 Письмо!</b>\n\n📧 <b>На почту:</b> <code>{}</code>\n👤 <b>От:</b> <code>{}</code>\n📝 <b>Тема:</b> {}\n\n<b>Текст:</b>\n<blockquote>{}</blockquote>"
    }

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        
        if not self.get("allowed_users"):
            self.set("allowed_users", [])
        if not self.get("emails"):
            self.set("emails", {})
            
        self.check_task = asyncio.create_task(self.mail_checker())

    async def on_unload(self):
        if hasattr(self, "check_task"):
            self.check_task.cancel()

    async def get_domain(self):
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{MAIL_API}/domains", timeout=10) as r:
                if r.status == 200:
                    data = await r.json()
                    domains = data.get("hydra:member", [])
                    if domains:
                        return domains[0]["domain"]
        return None

    async def _create_email(self):
        domain = await self.get_domain()
        if not domain: return None
        address = "".join(random.choices(string.ascii_lowercase + string.digits, k=10)) + f"@{domain}"
        password = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{MAIL_API}/accounts", json={"address": address, "password": password}, timeout=10) as r:
                if r.status not in (200, 201): return None
            async with s.post(f"{MAIL_API}/token", json={"address": address, "password": password}, timeout=10) as r:
                if r.status == 200:
                    t = await r.json()
                    return {"address": address, "password": password, "token": t.get("token")}
        return None

    async def _get_messages(self, token):
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{MAIL_API}/messages", headers={"Authorization": f"Bearer {token}"}, timeout=10) as r:
                if r.status == 200:
                    return (await r.json()).get("hydra:member", [])
        return []

    async def _get_msg_content(self, token, msg_id):
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{MAIL_API}/messages/{msg_id}", headers={"Authorization": f"Bearer {token}"}, timeout=10) as r:
                if r.status == 200:
                    return await r.json()
        return None

    def _format_body(self, body):
        """Вспомогательная функция для форматирования текста письма"""
        # Выделяем коды
        body = re.sub(r'(?<!\d)(\d{4,8})(?!\d)', lambda m: f"<code>{m.group(1)}</code>", body)
        body = re.sub(r'\b([A-Za-z0-9]{6,32})\b', lambda m: f"<code>{m.group(1)}</code>" if re.search(r'[A-Za-z]', m.group(1)) and re.search(r'\d', m.group(1)) else m.group(0), body)
        return body.replace("<", "&lt;").replace(">", "&gt;").replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")

    async def mail_checker(self):
        while True:
            await asyncio.sleep(15)
            try:
                now = time.time()
                emails = self.get("emails", {})
                updated = False
                for uid_str, data in list(emails.items()):
                    if data.get("expires_at", 0) < now:
                        del emails[uid_str]
                        updated = True
                        try: await self.client.send_message(int(uid_str), "<b>⌛ Время действия почты истекло.</b>")
                        except: pass
                        continue
                    token = data.get("token")
                    seen = data.get("seen_msgs", [])
                    try: messages = await self._get_messages(token)
                    except: continue
                    for msg in messages:
                        msg_id = msg.get("id")
                        if not msg_id or msg_id in seen: continue
                        seen.append(msg_id)
                        updated = True
                        try: full = await self._get_msg_content(token, msg_id)
                        except: full = None
                        src = full or msg
                        sender = src.get("from", {}).get("address", "???")
                        subject = src.get("subject", "(без темы)")
                        body = ""
                        if full:
                            body = full.get("text", "") or ""
                            if not body:
                                html_body = full.get("html", [""])[0] if isinstance(full.get("html"), list) else full.get("html", "")
                                body = re.sub(r"<[^>]+>", " ", html_body or "")
                                body = re.sub(r"\s+", " ", body).strip()
                        body = body.strip()[:3000] or "(пусто)"
                        body_fmt = self._format_body(body)
                        text = self.strings["new_mail"].format(data["address"], sender, subject.replace("<", "&lt;"), body_fmt)
                        try: await self.client.send_message(int(uid_str), text)
                        except: pass
                if updated: self.set("emails", emails)
            except Exception as e: logger.error(f"Checker error: {e}")

    @loader.command()
    async def tmailcmd(self, message: Message):
        """Создать временную почту"""
        await self._handle_mail_creation(message, message.sender_id)

    @loader.command()
    async def tmsgscmd(self, message: Message):
        """Посмотреть список входящих сообщений (ящик)"""
        await self._handle_view_inbox(message, message.sender_id)

    @loader.command()
    async def tmailclosecmd(self, message: Message):
        """Удалить почту"""
        uid_str = str(message.sender_id)
        emails = self.get("emails", {})
        if uid_str in emails:
            del emails[uid_str]
            self.set("emails", emails)
            await utils.answer(message, "<b>🗑 Почта удалена.</b>")
        else: await utils.answer(message, self.strings["no_email"])

    async def _handle_mail_creation(self, message, user_id):
        now = time.time()
        emails = self.get("emails", {})
        uid_str = str(user_id)
        if uid_str in emails and now - emails[uid_str].get("last_created", 0) < 30:
            return await utils.answer(message, self.strings["wait_cooldown"])
        status = await utils.answer(message, "<b>⏳ Создаю ящик...</b>")
        acc = await self._create_email()
        if not acc: return await utils.answer(status, "<b>❌ Ошибка API.</b>")
        expires_at = now + EMAIL_LIFETIME
        emails[uid_str] = {"address": acc["address"], "token": acc["token"], "expires_at": expires_at, "last_created": now, "seen_msgs": []}
        self.set("emails", emails)
        expire_str = time.strftime("%H:%M:%S", time.localtime(expires_at))
        text = self.strings["email_created"].format(acc['address'], expire_str)
        if message.is_private or message.out: await utils.answer(status, text)
        else:
            try:
                await self.client.send_message(user_id, text)
                await utils.answer(status, "<b>✅ Данные отправлены в ЛС.</b>")
            except: await utils.answer(status, "<b>❌ Напишите мне в ЛС первым.</b>")

    async def _handle_view_inbox(self, message, user_id):
        emails = self.get("emails", {})
        uid_str = str(user_id)
        if uid_str not in emails:
            return await utils.answer(message, self.strings["no_email"])
        
        status = await utils.answer(message, "<b>🔄 Проверяю ящик...</b>")
        data = emails[uid_str]
        try:
            msgs = await self._get_messages(data["token"])
        except:
            return await utils.answer(status, "<b>❌ Ошибка при получении писем.</b>")
            
        if not msgs:
            return await utils.answer(status, self.strings["inbox_empty"])
            
        res = ""
        for i, m in enumerate(msgs[:10], 1): # Показываем последние 10
            sender = m.get("from", {}).get("address", "???")
            subj = m.get("subject", "(без темы)")
            res += f"<b>{i}.</b> 👤 <code>{sender}</code>\n   📝 {subj[:50]}\n\n"
            
        text = self.strings["inbox_list"].format(len(msgs), res)
        if message.is_private or message.out: await utils.answer(status, text)
        else:
            try:
                await self.client.send_message(user_id, text)
                await utils.answer(status, "<b>📬 Список писем отправлен в ЛС.</b>")
            except: await utils.answer(status, "<b>❌ Напишите мне в ЛС.</b>")

    @loader.command()
    async def allowmailcmd(self, message: Message):
        """Добавить пользователя в белый список"""
        user = (await message.get_reply_message()).sender_id if message.is_reply else utils.get_args_raw(message)
        if not user: return await utils.answer(message, "<b>❌ Кого добавить?</b>")
        allowed = self.get("allowed_users", [])
        if user not in allowed:
            allowed.append(user)
            self.set("allowed_users", allowed)
        await utils.answer(message, self.strings["added_user"].format(user))

    @loader.watcher()
    async def watcher(self, message: Message):
        if not isinstance(message, Message) or not message.raw_text: return
        me = await self.client.get_me()
        if message.sender_id == me.id: return
        t = message.raw_text.lower()
        allowed = self.get("allowed_users", [])
        if message.sender_id in allowed:
            if t.startswith((".tmail", "/tmail")): await self._handle_mail_creation(message, message.sender_id)
            elif t.startswith((".tmsgs", "/tmsgs")): await self._handle_view_inbox(message, message.sender_id)
            elif t.startswith((".tmailclose", "/tmailclose")):
                # Логика закрытия (сокращено)
                emails = self.get("emails", {})
                if str(message.sender_id) in emails:
                    del emails[str(message.sender_id)]
                    self.set("emails", emails)
                    await utils.answer(message, "🗑 Удалено.")
