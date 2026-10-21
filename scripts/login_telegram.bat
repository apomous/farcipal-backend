@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python tg_login.py
pause
