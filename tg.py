"""Публичный Telegram через Telethon: глобальный поиск по имени + проверка типовых логинов.
Нужны TG_API_ID и TG_API_HASH (my.telegram.org) и один раз `python tg_login.py`.
Без них модуль молча отключается."""
import config  # noqa: F401  (грузит .env)
import asyncio
import os

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User

from core import norm

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
_client = None


async def get_client():
    global _client
    if not (API_ID and API_HASH):
        return None
    if _client is None:
        c = TelegramClient("tg_session", int(API_ID), API_HASH)
        await c.connect()
        if not await c.is_user_authorized():
            return None
        _client = c
    return _client


async def tg_candidates(q, nicks):
    """Возвращает список dict: id, first_name, last_name, username, about."""
    c = await get_client()
    if not c:
        return []
    qn = {norm(w) for w in q.names}
    found = {}
    try:
        res = await c(SearchRequest(q=" ".join(q.names), limit=20))
        for u in res.users:
            found[u.id] = u
        for nick in nicks[:8]:  # немного, чтобы не ловить FloodWait
            try:
                u = await c.get_entity(nick)
                if isinstance(u, User) and not u.bot:
                    found[u.id] = u
            except (ValueError, TypeError):
                pass
            await asyncio.sleep(1.5)
    except FloodWaitError:
        pass
    out = []
    for u in found.values():
        if u.deleted or u.bot:
            continue
        names = {norm(u.first_name), norm(u.last_name)}
        if not qn <= names:
            continue  # био запрашиваем только у подходящих по имени
        try:
            about = (await c(GetFullUserRequest(u))).full_user.about or ""
        except Exception:
            about = ""
        out.append(dict(id=u.id, first_name=u.first_name or "", last_name=u.last_name or "",
                        username=u.username or "", about=about))
    return out
