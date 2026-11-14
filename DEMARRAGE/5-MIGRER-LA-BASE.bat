@echo off
chcp 65001 >nul
REM Applique les migrations Django sur la base (DATABASE_URL de backend\.env).
cd /d "%~dp0..\backend"
.venv313\Scripts\python.exe manage.py migrate
pause
