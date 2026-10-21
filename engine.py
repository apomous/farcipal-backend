"""
Поисковое ядро (используют bot.py и web.py).
"""
import config  # noqa: F401  (грузит .env)
import asyncio
import logging
import json
import os
import re
import sqlite3
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import aiohttp
from playwright.async_api import async_playwright
from core import (MIN_SHOW, gen_nicks, link_candidates, parse_query, render_report,
                  score_tg, score_vk, score_web)
from tg import tg_candidates
from email_osint import email_intel
from nick_scanners import all_nick_scanners

VK_TOKEN = config.need("VK_TOKEN")
ALLOWED = {int(x) for x in os.getenv("ALLOWED_IDS", "").split(",") if x}
VK_V = "5.199"
REPORTS = Path("reports")
REPORTS.mkdir(exist_ok=True)

log = logging.getLogger("osint")

def setup_logging():
    if log.handlers: return
    h = RotatingFileHandler("osint.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(h)
setup_logging()

# ---------- очистка мусора ----------
def cleanup_reports_and_cache():
    """Удаляет старые отчеты сканеров и протухший кэш"""
    cutoff = time.time() - (7 * 86400)
    for f in REPORTS.rglob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
    try:
        db.execute("DELETE FROM cache WHERE ts < ?", (time.time() - 30 * 86400,))
        db.commit()
    except Exception as e:
        log.warning(f"Ошибка очистки кэша: {e}")

# ---------- кэш ----------
db = sqlite3.connect("cache.db")
db.execute("CREATE TABLE IF NOT EXISTS cache(k TEXT PRIMARY KEY, v TEXT, ts REAL)")

# очистка при старте (после создания БД, иначе чистить кэш нечем)
cleanup_reports_and_cache()

def cache_get(key, ttl=86400):
    row = db.execute("SELECT v, ts FROM cache WHERE k=?", (key,)).fetchone()
    return row[0] if row and time.time() - row[1] < ttl else None

def cache_set(key, val):
    db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, val, time.time()))
    db.commit()

# ---------- VK ----------
VK_FIELDS = ("bdate,city,home_town,status,site,domain,maiden_name,"
             "connections,has_photo,followers_count")

class VKError(Exception): pass

async def vk_call(method, **params):
    params.update(access_token=VK_TOKEN, v=VK_V, lang=0)
    async with aiohttp.ClientSession() as s:
        async with s.get(f"https://api.vk.com/method/{method}", params=params) as r:
            data = await r.json(content_type=None)
            if "error" in data:
                e = data["error"]
                raise VKError(f"{method}: код {e.get('error_code')}, {e.get('error_msg')}")
            return data.get("response")

_vk_search_ok = True

VK_HANDLE_RE = re.compile(r"https?://(?:m\.)?vk\.(?:com|ru)/([A-Za-z0-9_.]{3,32})(?:[/?#]|$)")
VK_SKIP_RE = re.compile(
    r"^(?:(?:club|public|event|wall|photo|video|album|topic|doc|app)\d+|away|feed|share|login|search|"
    r"friends|im|groups|audio|dev|id|apps|photos|albums|about|support|help|blog|terms|legal)$", re.I)

async def vk_via_web(q):
    name = " ".join(q.names)
    queries = [f"{name} site:vk.com"] + ([f"{name} {q.city} vk.com"] if q.city else [])
    batches = await asyncio.gather(*[search_engine(x, cfg) for x in queries for cfg in ENGINES.values()])
    handles = []
    for batch in batches:
        for _title, href, _snip in batch:
            m = VK_HANDLE_RE.match(href)
            if m and not VK_SKIP_RE.match(m.group(1)) and m.group(1) not in handles:
                handles.append(m.group(1))
    if not handles: return []
    return await vk_call("users.get", user_ids=",".join(handles[:50]), fields=VK_FIELDS) or []

async def vk_candidates(q, notes=None):
    global _vk_search_ok
    base = dict(fields=VK_FIELDS, count=200)
    if q.year: base["birth_year"] = q.year
    name = " ".join(q.names)
    calls = []
    if _vk_search_ok:
        calls.append(("поиск по ФИО", vk_call("users.search", q=name, **base)))
        if q.city:
            calls.append(("поиск по городу", vk_call("users.search", q=name, hometown=q.city, **base)))
    calls.append(("проверка логинов", vk_call("users.get", user_ids=",".join(gen_nicks(q)), fields=VK_FIELDS)))
    calls.append(("профили из веба", vk_via_web(q)))
    results = await asyncio.gather(*(c for _, c in calls), return_exceptions=True)
    users = {}
    for (label, _), r in zip(calls, results):
        if isinstance(r, Exception):
            log.warning("VK %s: %s", label, r)
            if label.startswith("поиск по") and ("код 1051" in str(r) or "код 28" in str(r)):
                _vk_search_ok = False
            elif notes is not None:
                notes.append(f"VK, {label}: {r}")
            continue
        items = r.get("items", []) if isinstance(r, dict) else r if isinstance(r, list) else []
        for u in items:
            users[u["id"]] = u
    if not _vk_search_ok and notes is not None:
        notes.append("ℹ️ VK не даёт этому ключу искать по ФИО (код 1051). Кандидаты берутся из веба и "
                     "по типовым логинам, поэтому покрытие меньше.")
    return list(users.values())

def fmt_vk(u):
    if u.get("deactivated"):
        return f"vk.com/id{u['id']} — {u['first_name']} {u['last_name']} ({u['deactivated']})"
    lines = [f"👤 {u['first_name']} {u['last_name']} — vk.com/{u.get('domain', 'id' + str(u['id']))}"]
    for key, label in [("bdate", "ДР"), ("home_town", "Родной город"), ("status", "Статус"), ("site", "Сайт")]:
        if u.get(key): lines.append(f"{label}: {u[key]}")
    if u.get("city"): lines.append(f"Город: {u['city']['title']}")
    if u.get("is_closed"): lines.append("🔒 профиль закрыт")
    return "\n".join(lines)

async def vk_by_id(ident):
    res = await vk_call("users.get", user_ids=ident, fields=VK_FIELDS)
    return "\n\n".join(fmt_vk(u) for u in res) if res else "VK: не найдено"

# ---------- Maigret ----------
async def maigret_urls(nick):
    out = REPORTS / f"report_{nick}_simple.json"
    out.unlink(missing_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "maigret", nick, "--json", "simple", "--folderoutput", str(REPORTS),
        "--timeout", "10", "--top-sites", "300", "--no-progressbar",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(proc.wait(), timeout=150)
    except asyncio.TimeoutError:
        proc.kill()
    if not out.exists(): return []
    data = json.loads(out.read_text(encoding="utf-8"))
    return [v["url_user"] for v in data.values() if v.get("url_user")]

# ---------- Комбайн сканеров (Maigret + Naminter + Aliens Eye + Argis) ----------
async def enrich_with_all_scanners(cands, progress=None):
    """Тот же ник на других площадках. Это справка: баллы не начисляем, ник не доказывает личность."""
    async def one(c):
        nick = c.url.rsplit("/", 1)[1]
        if re.fullmatch(r"id\d+", nick):
            return
        mg, extra = await asyncio.gather(maigret_urls(nick), all_nick_scanners(nick, REPORTS),
                                         return_exceptions=True)
        others = [u for u in (mg if isinstance(mg, list) else []) if "vk.com" not in u]
        if others:
            c.add("~", f"тот же ник (Maigret): {', '.join(others[:4])} — не подтверждено")
        found = []
        for scanner, rows in (extra if isinstance(extra, dict) else {}).items():
            found += [str(r.get("url") or r.get("name") or scanner) for r in rows[:2]]
        found = [x for x in dict.fromkeys(found) if x not in others][:5]
        if found:
            c.add("~", f"тот же ник (доп. сканеры): {', '.join(found)} — не подтверждено")

    await asyncio.gather(*(one(c) for c in cands), return_exceptions=True)


# ---------- веб через Playwright ----------
_pw = _browser = None
_sem = asyncio.Semaphore(2)
ENGINES = {
    "ddg": {"url": "https://html.duckduckgo.com/html/?q={q}", "item": ".result",
            "link": "a.result__a", "snippet": ".result__snippet"},
    "bing": {"url": "https://www.bing.com/search?q={q}&setlang=ru", "item": "li.b_algo",
             "link": "h2 a", "snippet": ".b_caption p"},
}

async def get_browser():
    global _pw, _browser
    if _browser is None:
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=True)
    return _browser

def clean_url(href):
    if "uddg=" in href:
        return unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
    return href

async def search_engine(query, cfg):
    async with _sem:
        ctx = await (await get_browser()).new_context(locale="ru-RU", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"))
        page = await ctx.new_page()
        found = []
        try:
            await page.goto(cfg["url"].format(q=quote_plus(query)), timeout=20000)
            await page.wait_for_selector(cfg["item"], timeout=8000)
            for it in (await page.query_selector_all(cfg["item"]))[:10]:
                a = await it.query_selector(cfg["link"])
                sn = await it.query_selector(cfg["snippet"])
                if a:
                    found.append(((await a.inner_text()).strip(),
                                  clean_url(await a.get_attribute("href") or ""),
                                  (await sn.inner_text()).strip() if sn else ""))
        except Exception:
            pass
        finally:
            await ctx.close()
        return found

async def web_hits(q):
    ctx = [""] + ([str(q.year)] if q.year else []) + ([q.city] if q.city else [])
    queries = [f'"{" ".join(q.names)}" {x}'.strip() for x in ctx]
    if q.patr: queries.append(f'"{q.full}"')
    batches = await asyncio.gather(*[search_engine(qq, cfg) for qq in queries for cfg in ENGINES.values()])
    seen, hits = set(), []
    for batch in batches:
        for title, href, snip in batch:
            if href in seen: continue
            seen.add(href)
            if c := score_web(q, title, snip, href):
                hits.append(c)
    return sorted(hits, key=lambda c: -c.score)

# ---------- Email OSINT ----------
EMAIL_RE = re.compile(r"^(?!-)[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

async def email_search(email: str, progress=None) -> str:
    if progress:
        await progress(f"Проверка {email} (Holehe + HIBP)…")
    data = await email_intel(email)
    out = [f"📧 Email: {email}", ""]
    used = data.get("registered_on", [])
    if used:
        out.append(f"✅ Регистрации ({len(used)}):")
        out += [f"• {site}" for site in used[:25]]
    else:
        out.append("❌ Регистрации: на проверяемых сервисах не найден.")
    out.append("")
    breaches = data.get("breaches", [])
    if breaches:
        names = ", ".join(str(b.get("Name", "?")) for b in breaches[:15])
        out.append(f"🔥 Утечки по Have I Been Pwned ({len(breaches)}): {names}")
    elif data.get("hibp_note"):
        out.append(f"ℹ️ HIBP: {data['hibp_note']}")
    else:
        out.append("🛡 В Have I Been Pwned не значится.")
    out += [f"⚠️ {e}" for e in data.get("errors", [])]
    return "\n".join(out)

# ---------- основной сценарий ----------
async def _tracked(name, coro, progress, on_done=None):
    try:
        result = await coro
        if on_done:
            try:
                await on_done(result)
            except Exception as e:  # noqa: BLE001
                log.warning("промежуточный результат %s: %r", name, e)
        return result
    finally:
        if progress:
            await progress(f"{name}: готово")


async def person_search_data(q, progress=None, notes=None, partial=None):
    """partial(kind, [dict]) вызывается, как только очередной модуль закончил (для живого интерфейса)."""
    t0 = time.time()
    nicks = gen_nicks(q)
    has_ctx = bool(q.year or q.city)

    async def part_vk(users):
        if partial and has_ctx:
            found = sorted(filter(None, (score_vk(q, u) for u in users)), key=lambda c: -c.score)
            await partial("vk", [c.to_dict() for c in found[:5] if c.score >= MIN_SHOW])

    async def part_web(hits):
        if partial:
            await partial("web", [c.to_dict() for c in hits[:6]])

    async def part_tg(tg_users):
        if partial:
            found = [c for c in filter(None, (score_tg(q, u, nicks) for u in tg_users)) if c.score >= MIN_SHOW]
            await partial("tg", [c.to_dict() for c in found[:3]])

    users, web, tg_users = await asyncio.gather(
        _tracked("VK", vk_candidates(q, notes), progress, part_vk),
        _tracked("Веб", web_hits(q), progress, part_web),
        _tracked("Telegram", tg_candidates(q, nicks), progress, part_tg),
        return_exceptions=True)
    for name, r in (("vk", users), ("web", web), ("tg", tg_users)):
        if isinstance(r, Exception):
            log.warning("модуль %s упал: %r", name, r)
            if notes is not None:
                notes.append(f"{name}: {r}")
    users = users if isinstance(users, list) else []
    web = web if isinstance(web, list) else []
    tg_users = tg_users if isinstance(tg_users, list) else []

    scored = sorted(filter(None, (score_vk(q, u) for u in users)), key=lambda c: -c.score)
    tg_scored = list(filter(None, (score_tg(q, u, nicks) for u in tg_users)))
    link_candidates(scored, tg_scored)

    top = [c for c in sorted(scored, key=lambda c: -c.score)[:5] if c.score >= MIN_SHOW] if has_ctx else []
    tg_top = sorted((c for c in tg_scored if c.score >= MIN_SHOW), key=lambda c: -c.score)[:3]

    if progress and top:
        await progress("Сканеры: проверяю логины…")
    await enrich_with_all_scanners(top[:2], progress)
    if progress and top:
        await progress("Сканеры: готово")

    log.info("поиск %r: vk=%d tg=%d web=%d за %.1f c", q.full, len(top), len(tg_top), len(web), time.time() - t0)
    return top, web, tg_top, len(scored)

async def person_search(q, progress=None):
    notes = []
    top, web, tg_top, total = await person_search_data(q, progress, notes)
    text = render_report(q, top, web, total, tg_top)
    if notes:
        text += "\n\n⚠️ Проблемы:\n" + "\n".join(notes)
    return text

VK_RE = re.compile(r"^(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([\w.]+)/?$|^(id\d+|\d+)$", re.I)
NICK_RE = re.compile(r"^[\w.][\w.-]{2,31}$")  # не начинается с "-" (иначе станет опцией программы)

async def run_query(text):
    text = text.strip()
    
    # НОВЫЙ РОУТИНГ: Если введен Email, запускаем Email OSINT
    if EMAIL_RE.match(text):
        return await email_search(text)
        
    if m := VK_RE.match(text):
        return await vk_by_id(m.group(1) or m.group(2))
    if q := parse_query(text):
        return await person_search(q)
    if NICK_RE.match(text):
        vk, urls = await asyncio.gather(vk_by_id(text), maigret_urls(text), return_exceptions=True)
        vk = vk if isinstance(vk, str) else f"VK: ошибка API — {vk}"
        acc = (f"🔎 Аккаунтов с таким ником: {len(urls)} (совпадение ника не доказывает, что это один человек)\n" 
               + "\n".join(urls[:30])) if isinstance(urls, list) and urls else "Maigret: ничего"
        return f"{vk}\n\n{acc}"
    return "Формат: «Иванов Иван Иванович 1990 Москва», ник, Email или ссылка/ID VK."