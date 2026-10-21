"""Запустить один раз (или login_telegram.bat). Данные берутся из .env.
Спросит номер и код, создаст файл tg_session.session. Лучше использовать отдельный аккаунт."""
import config  # noqa: F401  (грузит .env)
import os

from telethon.sync import TelegramClient

with TelegramClient("tg_session", int(config.need("TG_API_ID")), config.need("TG_API_HASH")) as c:
    print("Вход выполнен:", c.get_me().first_name)
