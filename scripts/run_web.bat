@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Сайт: http://localhost:8000  (логин и пароль из .env)
python -m uvicorn web:app --host 127.0.0.1 --port 8000
echo.
echo Сайт остановлен.
pause
