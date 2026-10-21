"""
Telegram-бот: тонкая обёртка над engine.py.
Запуск: BOT_TOKEN=... VK_TOKEN=... ALLOWED_IDS=123456 python bot.py
"""
import config  # noqa: F401  (грузит .env)
import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from engine import ALLOWED, cache_get, cache_set, run_query

BOT_TOKEN = config.need("BOT_TOKEN")
config.need("ALLOWED_IDS")  # без списка допущенных бот закрыт

# ---------- бот ----------
dp = Dispatcher()


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Пришлите «Иванов Иван Иванович 1990 Москва» (год и город повышают точность), ник или ссылку VK.")


@dp.message(F.text)
async def handle(m: Message):
    if m.from_user.id not in ALLOWED:
        return
    key = m.text.strip().lower()
    if cached := cache_get(key):
        return await m.answer(cached[:4000], disable_web_page_preview=True)
    wait = await m.answer("Ищу, это может занять до 2-3 минут…")
    try:
        result = await run_query(m.text)
    except Exception as e:  # noqa: BLE001
        result = f"Ошибка: {e}"
    cache_set(key, result)
    await wait.edit_text(result[:4000], disable_web_page_preview=True)


async def main():
    await dp.start_polling(Bot(BOT_TOKEN))


if __name__ == "__main__":
    asyncio.run(main())
