"""
Веб-интерфейс и REST API (Swagger: /docs).
Установка: pip install -r requirements.txt
Запуск:    python -m uvicorn web:app --host 127.0.0.1 --port 8000   (настройки берутся из .env)
Доступ закрыт паролем (HTTP Basic). Без WEB_PASS сервер не стартует.
Интерфейс: репозиторий farcipal-eye кладётся в папку ui (или путь в UI_DIR).
"""
import config  # noqa: F401  (грузит .env)
import asyncio
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import engine
from core import parse_query

WEB_USER = os.getenv("WEB_USER", "admin")
WEB_PASS = config.need("WEB_PASS")

security = HTTPBasic()


def auth(c: HTTPBasicCredentials = Depends(security)):
    ok = secrets.compare_digest(c.username.encode(), WEB_USER.encode()) and \
        secrets.compare_digest(c.password.encode(), WEB_PASS.encode())
    if not ok:
        raise HTTPException(401, "Нужен логин и пароль", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="OSINT", description="Поиск по открытым источникам", dependencies=[Depends(auth)])
BASE = Path(__file__).resolve().parent
UI_DIR = Path(os.getenv("UI_DIR") or BASE / "ui").expanduser()  # сюда кладётся репозиторий farcipal-eye
# check_dir=False: папку ui можно добавить, не пересоздавая приложение
app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True, check_dir=False), name="ui")

db = sqlite3.connect("web.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS searches(
    id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, created REAL, duration REAL,
    found INTEGER DEFAULT 0, status TEXT DEFAULT 'running', result TEXT)""")
db.execute("UPDATE searches SET status='error' WHERE status='running'")  # хвосты после перезапуска
db.commit()

PROGRESS: dict = {}
PARTIAL: dict = {}
SEM = asyncio.Semaphore(2)  # не больше двух тяжёлых поисков одновременно
TASKS: set = set()


class SearchIn(BaseModel):
    query: str


async def run_search(sid: int, text: str):
    t0 = time.time()

    async def progress(msg):
        PROGRESS[sid].append(msg)

    status, found = "done", 0
    notes = []

    async def partial(kind, items):
        PARTIAL[sid][kind] = items

    try:
        async with SEM:
            if q := parse_query(text):
                vk, web, tg, total = await engine.person_search_data(q, progress, notes, partial)
                web = web[:6]
                result = {"type": "person", "query": q.full, "year": q.year, "city": q.city,
                          "vk": [c.to_dict() for c in vk], "tg": [c.to_dict() for c in tg],
                          "web": [c.to_dict() for c in web], "vk_name_matches": total,
                          "need_context": not (q.year or q.city), "notes": notes}
                found = len(vk) + len(tg) + len(web)
            else:
                result = {"type": "text", "text": await engine.run_query(text)}
                found = 1
    except Exception as e:  # noqa: BLE001
        engine.log.exception("поиск %r упал", text)
        status, result = "error", {"type": "error", "text": f"Ошибка: {e}"}
    db.execute("UPDATE searches SET status=?, duration=?, found=?, result=? WHERE id=?",
               (status, time.time() - t0, found, json.dumps(result, ensure_ascii=False), sid))
    db.commit()
    PARTIAL.pop(sid, None)


@app.post("/search")
async def search(body: SearchIn):
    text = body.query.strip()
    if not 2 <= len(text) <= 200:
        raise HTTPException(400, "Запрос должен быть от 2 до 200 символов")
    cur = db.execute("INSERT INTO searches(query, created) VALUES(?,?)", (text, time.time()))
    db.commit()
    sid = cur.lastrowid
    PROGRESS[sid] = []
    PARTIAL[sid] = {}
    task = asyncio.create_task(run_search(sid, text))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {"id": sid}


@app.get("/result/{sid}")
def result(sid: int):
    row = db.execute("SELECT status, result, duration FROM searches WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "Поиск не найден")
    return {"id": sid, "status": row[0], "duration": row[2], "progress": PROGRESS.get(sid, []), "partial": PARTIAL.get(sid, {}),
            "result": json.loads(row[1]) if row[1] else None}


@app.get("/history")
def history(limit: int = 50):
    rows = db.execute("SELECT id, query, created, duration, found, status FROM searches "
                      "ORDER BY id DESC LIMIT ?", (min(limit, 200),)).fetchall()
    return [dict(id=r[0], query=r[1], created=r[2], duration=r[3], found=r[4], status=r[5]) for r in rows]


@app.get("/stats")
def stats():
    n, avg = db.execute("SELECT COUNT(*), AVG(duration) FROM searches WHERE status='done'").fetchone()
    pop = db.execute("SELECT query, COUNT(*) c FROM searches GROUP BY query ORDER BY c DESC LIMIT 5").fetchall()
    return {"done": n, "avg_seconds": round(avg or 0, 1), "popular": [{"query": q, "count": c} for q, c in pop]}


@app.get("/health")
def health():
    return {"ok": True}


NO_UI_PAGE = """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Farcipal backend</title>
<body style="font-family:system-ui,sans-serif;background:#09090f;color:#d7dae4;max-width:640px;margin:12vh auto;padding:0 20px;line-height:1.6">
<h1 style="color:#3dcf6f">Farcipal backend работает</h1>
<p>Интерфейс не найден. Выполните в папке проекта:</p>
<pre style="background:#12121c;padding:14px;border-radius:10px;overflow:auto">git clone https://github.com/apomous/farcipal-eye.git ui</pre>
<p>и обновите страницу. Или укажите путь к интерфейсу в <code>UI_DIR</code> в файле <code>.env</code>.</p>
<p>REST API и документация доступны уже сейчас: <a style="color:#a5b4fc" href="/docs">/docs</a></p>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    if (UI_DIR / "index.html").exists():
        return RedirectResponse("/ui/")
    return HTMLResponse(NO_UI_PAGE)
