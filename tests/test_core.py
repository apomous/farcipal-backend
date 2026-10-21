from core import (Query, gen_nicks, link_candidates, parse_query, render_report,
                  score_tg, score_vk, score_web)

GOOD = {"id": 1, "first_name": "Иван", "last_name": "Иванов", "domain": "ivan_ivanov",
        "bdate": "5.3.1990", "city": {"title": "Москва"}}


def test_parse_full():
    q = parse_query("Иванов Иван Иванович 1990 Москва")
    assert q == Query(["Иванов", "Иван"], "Иванович", 1990, "Москва")


def test_parse_city_without_patronymic():
    q = parse_query("Иван Петров Санкт-Петербург")
    assert q.patr == "" and q.city == "Санкт-Петербург" and q.year is None


def test_parse_rejects_nick():
    assert parse_query("durov") is None


def test_gen_nicks_contains_typical():
    nicks = gen_nicks(parse_query("Иванов Иван 1990"))
    assert "ivan_ivanov" in nicks and "ivanov.ivan" in nicks and "iivanov" in nicks
    assert "ivanivanov90" in nicks and all(4 <= len(n) <= 32 for n in nicks)


def test_vk_full_match():
    c = score_vk(parse_query("Иванов Иван 1990 Москва"), GOOD)
    assert c.score == 100 or c.score >= 80
    assert any(p == 35 for _, _, p in c.evidence)


def test_vk_wrong_year_rejected():
    assert score_vk(parse_query("Иванов Иван 1990"), dict(GOOD, bdate="1.1.1985")) is None


def test_vk_wrong_city_penalised_not_rejected():
    c = score_vk(parse_query("Иванов Иван 1990 Москва"), dict(GOOD, city={"title": "Казань"}))
    assert c is not None and c.score < 80


def test_vk_other_name_rejected():
    assert score_vk(parse_query("Иванов Иван"), dict(GOOD, first_name="Пётр")) is None


def test_web_requires_context():
    q = parse_query("Иванов Иван 1990 Москва")
    assert score_web(q, "Иванов Иван блог", "тест", "https://blog.example.com") is None
    assert score_web(q, "Иванов Иван", "ИП, Москва, 1990", "https://www.rusprofile.ru/x") is not None


def test_tg_and_link():
    q = parse_query("Иванов Иван 1990 Москва")
    vk = [score_vk(q, GOOD)]
    tg = [score_tg(q, {"id": 9, "first_name": "Иван", "last_name": "Иванов",
                       "username": "ivan_ivanov", "about": "Москва"}, gen_nicks(q))]
    before = tg[0].score
    link_candidates(vk, tg)
    assert tg[0].score == before + 30
    assert "t.me/ivan_ivanov" in render_report(q, vk, [], 1, tg)


def test_parse_full_date():
    q = parse_query("Иванов Иван 16.04.1990")
    assert q.year == 1990 and q.bday == (16, 4) and q.city == ""


def test_vk_day_month_when_year_hidden():
    q = parse_query("Иванов Иван 05.03.1990")
    c = score_vk(q, dict(GOOD, bdate="5.3"))
    assert c is not None and c.score == 60
    assert score_vk(q, dict(GOOD, bdate="6.3")) is None
