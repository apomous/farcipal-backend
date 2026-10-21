"""Проверка VK-ключа: показывает настоящий ответ VK. Запуск: check_vk.bat"""
import json
import urllib.parse
import urllib.request

import config

TOKEN = config.need("VK_TOKEN")
HINTS = {
    5: "Ключ недействителен. Проверьте, что в .env именно «Сервисный ключ доступа», что он скопирован целиком, а приложение включено.",
    28: "Неверный тип ключа. Нужен именно сервисный ключ приложения.",
    15: "Доступ запрещён: профиль скрыт или метод недоступен этому ключу.",
    27: "Этот метод недоступен с ключом сообщества. Нужен ключ приложения.",
    100: "Один из параметров запроса неверный.",
    113: "Такого пользователя нет.",
}


def call(method, **params):
    params.update(access_token=TOKEN, v="5.199")
    url = f"https://api.vk.com/method/{method}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def show(title, data):
    print(f"\n--- {title} ---")
    if "error" in data:
        e = data["error"]
        print(f"ОШИБКА {e.get('error_code')}: {e.get('error_msg')}")
        print(HINTS.get(e.get("error_code"), "Расшифровки нет, пришлите этот текст разработчику."))
    else:
        print("OK:", json.dumps(data["response"], ensure_ascii=False)[:300])


print("Длина ключа:", len(TOKEN), "(сервисный ключ обычно около 85 символов)")
show("users.get по ID 1", call("users.get", user_ids="1"))
nick = input("\nВведите свой ник VK (часть после vk.com/): ").strip()
if nick:
    show(f"users.get по нику {nick}", call("users.get", user_ids=nick, fields="bdate,city,domain"))
show("users.search (поиск по имени)", call("users.search", q="Иван Иванов", count=1))
input("\nНажмите Enter, чтобы закрыть…")
