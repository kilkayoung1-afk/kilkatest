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
    """Модуль для создания временных почт (mail.tm). Поддерживает выдачу доступа другим пользователям."""
    
    strings = {
        "name": "TempMail",
        "email_created": "<b>✅ Временная почта создана!</b>\n\n📧 <b>Адрес:</b> <code>{}</code>\n⏳ <b>Действует до:</b> <code>{}</code>\n\n<i>Письма будут приходить сюда автоматически.</i>",
        "wait_cooldown": "<b>⏳ Подождите, создавать почту можно не чаще раза в 30 секунд.</b>",
        "added_user": "<b>✅ Пользователь <code>{}</code> добавлен в список доверенных.</b>",
        "removed_user": "<b>❌ Пользователь <code>{}</code> удален из списка доверенных.</b>",
        "no_email": "<b>❌ Активная почта не найдена.</b>",
        "new_mail": "<b>📨 Новое письмо!</b>\n\n📧 <b>На почту:</b> <code>{}</code>\n👤 <b>От:</b> <code>{}</code>\n📝 <b>Тема:</b> {}\n\n<b>Текст:</b>\n<blockquote>{}</blockquote>"
    }

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        
        # Инициализация хранилища в БД модуля
        if not self.get("allowed_users"):
            self.set("allowed_users", [])
        if not self.get("emails"):
            self.set("emails", {})
            
        # Запускаем фоновую задачу на проверку писем
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
        if not domain: 
            return None
            
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

    async def mail_checker(self):
        """Фоновый луп для проверки новых писем (каждые 15 секунд)"""
        while True:
            await asyncio.sleep(15)
            try:
                now = time.time()
                emails = self.get("emails", {})
                updated = False
                
                for uid_str, data in list(emails.items()):
                    # Если время почты истекло
                    if data.get("expires_at", 0) < now:
                        del emails[uid_str]
                        updated = True
                        try:
                            await self.client.send_message(int(uid_str), "<b>⌛ Время действия вашей временной почты истекло.</b>")
                        except:
                            pass
                        continue
                    
                    token = data.get("token")
                    seen = data.get("seen_msgs", [])
                    
                    try:
                        messages = await self._get_messages(token)
                    except:
                        continue
                        
                    for msg in messages:
                        msg_id = msg.get("id")
                        if not msg_id or msg_id in seen:
                            continue
                            
                        seen.append(msg_id)
                        updated = True
                        
                        try:
                            full = await self._get_msg_content(token, msg_id)
                        except:
                            full = None
                            
                        src = full or msg
                        sender = src.get("from", {}).get("address", "???")
                        subject = src.get("subject", "(без темы)")
                        
                        # Парсинг тела письма
                        body = ""
                        if full:
                            body = full.get("text", "") or ""
                            if not body:
                                html_body = full.get("html", [""])[0] if isinstance(full.get("html"), list) else full.get("html", "")
                                body = re.sub(r"<[^>]+>", " ", html_body or "")
                                body = re.sub(r"\s+", " ", body).strip()
                        body = body.strip()[:3000] or "(пусто)"
                        
                        # Выделяем коды для копирования в одно нажатие
                        body = re.sub(r'(?<!\d)(\d{4,8})(?!\d)', lambda m: f"<code>{m.group(1)}</code>", body)
                        body = re.sub(r'\b([A-Za-z0-9]{6,32})\b', lambda m: f"<code>{m.group(1)}</code>" if re.search(r'[A-Za-z]', m.group(1)) and re.search(r'\d', m.group(1)) else m.group(0), body)
                        
                        body_escaped = body.replace("<", "&lt;").replace(">", "&gt;").replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
                        subject_escaped = subject.replace("<", "&lt;").replace(">", "&gt;")
                        
                        text = self.strings["new_mail"].format(data["address"], sender, subject_escaped, body_escaped)
                        
                        # Отправляем сообщение напрямую пользователю
                        try:
                            await self.client.send_message(int(uid_str), text)
                        except Exception as e:
                            logger.error(f"Failed to send mail to {uid_str}: {e}")
                            
                if updated:
                    self.set("emails", emails)
            except Exception as e:
                logger.error(f"Mail checker error: {e}")

    async def _handle_mail_creation(self, message: Message, user_id: int):
        """Вспомогательный метод для генерации почты"""
        now = time.time()
        emails = self.get("emails", {})
        uid_str = str(user_id)
        is_pm = message.is_private
        
        if uid_str in emails:
            data = emails[uid_str]
            if now - data.get("last_created", 0) < 30:
                await utils.answer(message, self.strings["wait_cooldown"])
                return
                
        status_msg = await utils.answer(message, "<b>⏳ Создаю почту...</b>")
        
        acc = await self._create_email()
        if not acc:
            await utils.answer(status_msg, "<b>❌ Ошибка API mail.tm</b>")
            return
            
        expires_at = now + EMAIL_LIFETIME
        emails[uid_str] = {
            "address": acc["address"],
            "token": acc["token"],
            "expires_at": expires_at,
            "last_created": now,
            "seen_msgs": []
        }
        self.set("emails", emails)
        
        expire_str = time.strftime("%H:%M:%S", time.localtime(expires_at))
        text = self.strings["email_created"].format(acc['address'], expire_str)
        
        # Если это чат, отправляем в ЛС (чтобы другие не видели почту), если ЛС — редактируем/отвечаем
        if is_pm or message.out:
            await utils.answer(status_msg, text)
        else:
            try:
                await self.client.send_message(user_id, text)
                await utils.answer(status_msg, "<b>✅ Почта успешно создана и отправлена вам в ЛС!</b>")
            except Exception:
                await utils.answer(status_msg, "<b>❌ Не удалось отправить почту. Напишите мне в личные сообщения первым!</b>")

    @loader.command()
    async def tmailcmd(self, message: Message):
        """Создать временную почту"""
        await self._handle_mail_creation(message, message.sender_id)

    @loader.command()
    async def tmailclosecmd(self, message: Message):
        """Удалить активную почту досрочно"""
        uid_str = str(message.sender_id)
        emails = self.get("emails", {})
        if uid_str in emails:
            del emails[uid_str]
            self.set("emails", emails)
            await utils.answer(message, "<b>🗑 Почта успешно удалена.</b>")
        else:
            await utils.answer(message, self.strings["no_email"])

    @loader.command()
    async def allowmailcmd(self, message: Message):
        """<@user | reply> - Разрешить пользователю создавать почту"""
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()
        user = None
        
        if reply:
            user = reply.sender_id
        elif args:
            try:
                user_entity = await self.client.get_entity(args)
                user = user_entity.id
            except:
                return await utils.answer(message, "<b>❌ Пользователь не найден.</b>")
                
        if not user:
            return await utils.answer(message, "<b>❌ Укажите пользователя (реплай или @username).</b>")
            
        allowed = self.get("allowed_users", [])
        if user not in allowed:
            allowed.append(user)
            self.set("allowed_users", allowed)
            
        await utils.answer(message, self.strings["added_user"].format(user))

    @loader.command()
    async def denymailcmd(self, message: Message):
        """<@user | reply> - Запретить пользователю создавать почту"""
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()
        user = None
        
        if reply:
            user = reply.sender_id
        elif args:
            try:
                user_entity = await self.client.get_entity(args)
                user = user_entity.id
            except:
                return await utils.answer(message, "<b>❌ Пользователь не найден.</b>")
                
        if not user:
            return await utils.answer(message, "<b>❌ Укажите пользователя (реплай или @username).</b>")
            
        allowed = self.get("allowed_users", [])
        if user in allowed:
            allowed.remove(user)
            self.set("allowed_users", allowed)
            
        await utils.answer(message, self.strings["removed_user"].format(user))

    @loader.watcher()
    async def watcher(self, message: Message):
        """Перехватчик сообщений для работы команд у доверенных пользователей"""
        if not isinstance(message, Message) or not message.raw_text:
            return
            
        me = await self.client.get_me()
        if message.sender_id == me.id:
            return  # Свои команды обрабатываются через @loader.command
            
        text = message.raw_text.lower()
        if text.startswith((".tmail", "/tmail")):
            allowed = self.get("allowed_users", [])
            if message.sender_id in allowed:
                if text.startswith((".tmailclose", "/tmailclose")):
                    uid_str = str(message.sender_id)
                    emails = self.get("emails", {})
                    if uid_str in emails:
                        del emails[uid_str]
                        self.set("emails", emails)
                        await utils.answer(message, "<b>🗑 Почта успешно удалена.</b>")
                    else:
                        await utils.answer(message, self.strings["no_email"])
                else:
                    await self._handle_mail_creation(message, message.sender_id)
