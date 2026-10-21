"""Чистая логика без сети: разбор запроса, генерация ников, оценка совпадений, отчёт."""
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.((?:19|20)\d{2})$")
WORD_RE = re.compile(r"^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]*$")
PATR_SUF = ("ович", "евич", "ьич", "овна", "евна", "ична", "ич")
MIN_SHOW = 55  # ниже этого порога совпадения не показываем

REGISTRY = ("rusprofile.ru", "list-org.com", "checko.ru", "zachestnyibiznes.ru",
            "sbis.ru", "egrul.nalog.ru", "fedresurs.ru", "kad.arbitr.ru", "e-disclosure.ru")
SOCIAL = ("vk.com", "ok.ru", "linkedin.com", "habr.com", "github.com", "instagram.com",
          "t.me", "facebook.com", "twitter.com", "x.com")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


# ---------- запрос ----------
@dataclass
class Query:
    names: list
    patr: str = ""
    year: int | None = None
    city: str = ""
    bday: tuple | None = None  # (день, месяц), если указана полная дата

    @property
    def full(self) -> str:
        return " ".join(self.names + ([self.patr] if self.patr else []))


def parse_query(text: str):
    """«Иванов Иван Иванович 1990 Москва» -> Query. Год, отчество, город необязательны."""
    toks = [t.strip(".,;") for t in text.split()]
    year, bday, rest = None, None, []
    for t in toks:
        if (m := DATE_RE.match(t)) and year is None:
            bday, year = (int(m.group(1)), int(m.group(2))), int(m.group(3))
        elif YEAR_RE.match(t) and year is None:
            year = int(t)
        elif t:
            rest.append(t)
    if len(rest) < 2 or not all(WORD_RE.match(w) for w in rest):
        return None
    names, rest = rest[:2], rest[2:]
    patr = ""
    if rest and len(rest[0]) >= 6 and norm(rest[0]).endswith(PATR_SUF):
        patr, rest = rest[0], rest[1:]
    return Query(names, patr, year, " ".join(rest), bday)


# ---------- ники ----------
_T = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
      "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
      "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
      "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "-": ""}


def translit_variants(word: str) -> set:
    w = norm(word).replace("-", "")
    if re.search("[a-z]", w):
        return {w}
    base = "".join(_T.get(c, c) for c in w)
    short = re.sub(r"(iy|yy|ij)$", "y", base.replace("kh", "h"))
    return {base, short}


def gen_nicks(q: Query) -> list:
    """Типовые логины из ФИО: ivanpetrov, i.petrov, petrov_ivan90 ..."""
    out = set()
    for fa in translit_variants(q.names[0]):
        for fb in translit_variants(q.names[1]):
            for x, y in ((fa, fb), (fb, fa)):
                out.update({x + y, x + "." + y, x + "_" + y, x[0] + y, x + y[0]})
                if q.year:
                    y4 = str(q.year)
                    for sep in ("", "_"):
                        out.update({x + sep + y + y4[2:], x + sep + y + y4})
    return sorted(n for n in out if 4 <= len(n) <= 32)


# ---------- кандидаты ----------
@dataclass
class Candidate:
    source: str
    url: str
    title: str
    score: int = 0
    evidence: list = field(default_factory=list)
    links: list = field(default_factory=list)

    def add(self, mark: str, text: str, pts: int = 0):
        self.evidence.append((mark, text, pts))
        self.score += pts

    def to_dict(self) -> dict:
        s = max(0, min(100, self.score))
        return {"source": self.source, "url": self.url, "title": self.title, "score": s,
                "label": label(s), "links": self.links,
                "evidence": [{"mark": m, "text": t, "pts": p} for m, t, p in self.evidence]}

    def render(self, i: int) -> str:
        s = max(0, min(100, self.score))
        lines = [f"{i}. {self.title[:70]} — {s}% ({label(s)})", self.url]
        lines += [f"   {m} {t}" + (f" ({p:+d})" if p else "") for m, t, p in self.evidence]
        if self.links:
            lines.append("   🔗 в профиле: " + ", ".join(self.links))
        return "\n".join(lines)


def label(score: int) -> str:
    return "высокая" if score >= 80 else "средняя" if score >= 55 else "низкая"


def score_vk(q: Query, u: dict):
    """Оценка VK-профиля. None — профиль точно не тот."""
    if u.get("deactivated"):
        return None
    qn = {norm(w) for w in q.names}
    pn = {norm(u.get("first_name")), norm(u.get("last_name")), norm(u.get("maiden_name"))}
    if not qn <= pn:
        return None
    dom = u.get("domain") or f"id{u['id']}"
    c = Candidate("vk", f"https://vk.com/{dom}", f"{u.get('first_name', '')} {u.get('last_name', '')}")
    c.add("✓", "ФИО совпало", 40)

    bd = (u.get("bdate") or "").split(".")
    if q.bday and len(bd) >= 2:
        if (int(bd[0]), int(bd[1])) != q.bday:
            return None  # день или месяц рождения не тот
        c.add("✓", f"день и месяц рождения {bd[0]}.{bd[1]}", 20)
    if len(bd) == 3:
        if q.year:
            if int(bd[2]) != q.year:
                return None  # год рождения не тот — отбрасываем
            c.add("✓", f"год рождения {q.year}", 35)
        else:
            c.add("~", f"дата рождения {u['bdate']}")
    elif q.year:
        c.add("~", "год рождения скрыт")

    if q.city:
        qc = norm(q.city)
        shown = [(u.get("city") or {}).get("title", ""), u.get("home_town") or ""]
        shown = [p for p in shown if p]
        if any(norm(p) and (qc in norm(p) or norm(p) in qc) for p in shown):
            c.add("✓", f"город {q.city}", 25)
        elif shown:
            c.add("✗", f"город в профиле: {shown[0]}", -10)
        else:
            c.add("~", "город скрыт")

    if u.get("is_closed"):
        c.add("~", "профиль закрыт, данных мало")
    for key, base in (("instagram", "instagram.com/"), ("twitter", "twitter.com/"),
                      ("facebook", "facebook.com/"), ("livejournal", "livejournal.com/")):
        if u.get(key):
            c.links.append(base + str(u[key]).lstrip("@"))
    if u.get("site"):
        c.links.append(u["site"])
    return c


def score_web(q: Query, title: str, snippet: str, url: str):
    """Оценка веб-результата по контексту. None — ниже порога."""
    text = norm(title + " " + snippet)
    if not all(norm(w) in text for w in q.names):
        return None
    host = urlparse(url).netloc.lower().removeprefix("www.")
    c = Candidate("web", url, title)
    c.add("✓", "ФИО в тексте", 40)
    if q.patr and norm(q.patr) in text:
        c.add("✓", "отчество совпало", 20)
    if q.year and str(q.year) in text:
        c.add("✓", f"упомянут {q.year}", 20)
    if q.city and norm(q.city) in text:
        c.add("✓", f"упомянут {q.city}", 20)
    if any(host.endswith(d) for d in REGISTRY):
        c.add("✓", "открытый реестр", 20)
    elif any(host.endswith(d) for d in SOCIAL):
        c.add("~", "профиль на площадке", 10)
    return c if c.score >= MIN_SHOW else None


# ---------- отчёт ----------
def score_tg(q: Query, u: dict, nicks: list):
    """Оценка публичного Telegram-аккаунта: имя, био (год/город), логин."""
    qn = {norm(w) for w in q.names}
    pn = {norm(u.get("first_name")), norm(u.get("last_name"))}
    if not qn <= pn:
        return None
    uname = u.get("username") or ""
    c = Candidate("tg", f"https://t.me/{uname}" if uname else f"tg id {u['id']}",
                  f"{u.get('first_name', '')} {u.get('last_name', '')}".strip())
    c.add("✓", "ФИО совпало", 40)
    about = norm(u.get("about"))
    if q.year and str(q.year) in about:
        c.add("✓", f"в био упомянут {q.year}", 20)
    if q.city and norm(q.city) in about:
        c.add("✓", f"в био упомянут {q.city}", 20)
    if uname and uname.lower() in nicks:
        c.add("~", "логин похож на ФИО", 5)
    if about:
        c.add("~", f"био: {about[:80]}")
    return c


def link_candidates(vk: list, tg: list):
    """Склейка: один и тот же логин у VK- и TG-кандидата усиливает оба."""
    by_dom = {c.url.rsplit("/", 1)[1].lower(): c for c in vk}
    for t in tg:
        uname = t.url.rsplit("/", 1)[1].lower()
        if (v := by_dom.get(uname)) and not uname.startswith("id"):
            t.add("✓", "тот же логин, что у VK-кандидата", 30)
            v.add("✓", f"тот же логин в Telegram: {t.url}", 10)


def render_report(q: Query, vk: list, web: list, vk_total: int, tg: list | None = None) -> str:
    head = f"📋 {q.full}" + (f", {q.year}" if q.year else "") + (f", {q.city}" if q.city else "")
    out = [head]
    if not (q.year or q.city):
        out.append(f"⚠️ Без года рождения или города точность низкая: в VK не меньше {vk_total} "
                   f"профилей с таким ФИО. Пример запроса: «{q.full} 1990 Москва».")
    if vk:
        out.append("🎯 VK, вероятные совпадения:\n" + "\n\n".join(c.render(i) for i, c in enumerate(vk, 1)))
    elif q.year or q.city:
        out.append("VK: подходящих профилей не найдено.")
    if tg:
        out.append("✈️ Telegram, вероятные совпадения:\n" + "\n\n".join(c.render(i) for i, c in enumerate(tg, 1)))
    if web:
        out.append("🌐 Веб, значимые упоминания:\n" + "\n\n".join(c.render(i) for i, c in enumerate(web[:6], 1)))
    elif q.year or q.city:
        out.append("Веб: значимых упоминаний не найдено.")
    return "\n\n".join(out)
