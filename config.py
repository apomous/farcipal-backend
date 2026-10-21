"""Загружает настройки из файла .env (лежит рядом с кодом). Импортируется первым."""
import os
from pathlib import Path

_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:  # пустые значения считаем незаданными
            os.environ.setdefault(key.strip(), value)


def need(name: str) -> str:
    """Возвращает значение или останавливает программу с понятным сообщением."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"\nНе заполнено {name} в файле .env\n(откройте .env в блокноте, впишите значение и сохраните)\n")
    return value
