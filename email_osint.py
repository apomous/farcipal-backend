"""Email-OSINT: Holehe (на каких сервисах зарегистрирован адрес) + Have I Been Pwned (в каких утечках встречался).
HIBP требует платный API-ключ (HIBP_API_KEY в .env); без него эта часть пропускается.
Проверяйте только свои адреса или адреса с согласия владельца."""
import asyncio
import os
import re
from urllib.parse import quote

import aiohttp

UA = "osint-bot/1.0 (personal research)"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


async def holehe_used(email: str) -> list:
    try:
        proc = await asyncio.create_subprocess_exec(
            "holehe", email, "--only-used",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError:
        raise RuntimeError("Holehe не установлен (pip install holehe)")
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Holehe не ответил за 120 секунд")
    text = ANSI_RE.sub("", stdout.decode("utf-8", errors="replace"))
    used = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("[+]"):
            continue
        parts = line[3:].split()
        site = parts[0] if parts else ""
        # легенду вида "[+] Email used, [-] ..." отсекаем: у настоящего сайта в названии есть точка
        if DOMAIN_RE.match(site) and site not in used:
            used.append(site)
    return used


async def hibp_breaches(email: str):
    """-> (список утечек, пояснение). Без ключа проверка пропускается."""
    key = os.getenv("HIBP_API_KEY")
    if not key:
        return [], "ключ HIBP_API_KEY не задан в .env, проверка утечек пропущена"
    url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(email)}"
    headers = {"user-agent": UA, "hibp-api-key": key}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers, params={"truncateResponse": "true"}) as r:
            if r.status == 404:
                return [], None
            if r.status == 401:
                return [], "HIBP не принял ключ (401)"
            if r.status == 429:
                return [], "HIBP: слишком много запросов (429), попробуйте позже"
            if r.status != 200:
                return [], f"HIBP: ответ HTTP {r.status}"
            return await r.json(), None


async def email_intel(email: str) -> dict:
    used_r, hibp_r = await asyncio.gather(holehe_used(email), hibp_breaches(email), return_exceptions=True)
    errors, used, breaches, note = [], [], [], None
    if isinstance(used_r, Exception):
        errors.append(str(used_r))
    else:
        used = used_r
    if isinstance(hibp_r, Exception):
        errors.append(f"HIBP: {hibp_r}")
    else:
        breaches, note = hibp_r
    return {"email": email, "registered_on": used, "breaches": breaches, "hibp_note": note, "errors": errors}
