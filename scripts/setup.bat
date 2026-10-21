@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === Установка библиотек (займёт несколько минут) ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Создан файл .env. Сейчас он откроется: впишите ключи и сохраните.
  notepad .env
)
echo.
echo Готово. Дальше: scripts\run_bot.bat или scripts\run_web.bat
pause
