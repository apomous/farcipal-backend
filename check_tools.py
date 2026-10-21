"""Показывает, какие внешние программы установлены, и их справку (--help)."""
import shutil
import subprocess

for tool in ["maigret", "holehe", "naminter", "aliens_eye", "argis"]:
    print(f"\n=== {tool} ===")
    if not shutil.which(tool):
        print("НЕ УСТАНОВЛЕН")
        continue
    try:
        r = subprocess.run([tool, "--help"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=40)
        print("\n".join((r.stdout or r.stderr).splitlines()[:25]))
    except Exception as e:  # noqa: BLE001
        print("ошибка запуска:", e)
input("\nНажмите Enter, чтобы закрыть…")
