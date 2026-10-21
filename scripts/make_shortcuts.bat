@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcuts.ps1"
echo.
echo Готово: ярлыки на рабочем столе. Папку с программой не переносите.
pause
