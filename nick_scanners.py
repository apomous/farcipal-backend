"""Дополнительные сканеры ников (кроме Maigret). По умолчанию ВЫКЛЮЧЕНЫ.
Включаются в .env: EXTRA_SCANNERS=naminter   (можно через запятую: naminter,aliens,argis)

Флаги командной строки у этих программ зависят от версии. Перед включением запустите
check_tools.bat и сверьте вывод --help с командами ниже."""
import asyncio
import json
import os
import shutil
from pathlib import Path


async def _run(cmd: list, timeout: int = 90):
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    except (FileNotFoundError, OSError, NotImplementedError):
        return None
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
    return proc.returncode


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rows(data) -> list:
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("results") or data.get("profiles") or []
    else:
        rows = []
    return [r for r in rows if isinstance(r, dict)]


def _norm(row: dict) -> dict:
    return {"url": row.get("url") or row.get("url_user") or row.get("profile_url") or "",
            "name": row.get("name") or row.get("site") or row.get("site_name") or ""}


async def naminter_hits(nick: str, d: Path) -> list:
    out = d / "naminter.json"
    await _run(["naminter", "--username", nick, "--json", "--json-path", str(out)])
    hits = []
    for r in _rows(_load(out)):
        st = r.get("result_status")
        value = st.get("value") if isinstance(st, dict) else st
        if value == "found" or r.get("found") is True:
            hits.append(_norm(r))
    return hits


async def aliens_hits(nick: str, d: Path) -> list:
    await _run(["aliens_eye", nick, "--format", "json", "--output", str(d)], timeout=120)
    for f in sorted(d.rglob("*.json")):  # только внутри своей папки, чужие отчёты не трогаем
        rows = [r for r in _rows(_load(f)) if str(r.get("status", "")).lower() in ("found", "maybe")]
        if rows:
            return [_norm(r) for r in rows]
    return []


async def argis_hits(nick: str, d: Path) -> list:
    out = d / "argis.json"
    await _run(["argis", "scan", nick, "--export", "json", "-o", str(out)])
    return [_norm(r) for r in _rows(_load(out)) if str(r.get("status", "")).upper() == "FOUND"]


SCANNERS = {"naminter": ("naminter", naminter_hits),
            "aliens": ("aliens_eye", aliens_hits),
            "argis": ("argis", argis_hits)}


async def all_nick_scanners(nick: str, out_dir: Path) -> dict:
    """-> {имя_сканера: [{'url','name'}]}. Пусто, если ничего не включено или программа не установлена."""
    enabled = [n.strip() for n in os.getenv("EXTRA_SCANNERS", "").split(",") if n.strip()]
    todo = [(n, SCANNERS[n][1]) for n in enabled if n in SCANNERS and shutil.which(SCANNERS[n][0])]
    if not todo or nick.startswith("-"):
        return {}
    jobs = []
    for name, fn in todo:
        d = out_dir / "scanners" / nick / name  # у каждого сканера своя папка
        d.mkdir(parents=True, exist_ok=True)
        jobs.append(fn(nick, d))
    results = await asyncio.gather(*jobs, return_exceptions=True)
    return {name: (r if isinstance(r, list) else []) for (name, _), r in zip(todo, results)}
