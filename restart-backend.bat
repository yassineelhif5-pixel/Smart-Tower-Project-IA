@echo off
chcp 65001 >nul
REM Redemarre uniquement le backend (apres une modification du code Python ou du fichier .env).
set ROOT=%~dp0.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq PCT Backend (Django)*" >nul 2>&1
cd /d "%ROOT%\backend"
.venv313\Scripts\python.exe -m pip install -q -r requirements.txt > pip_log.txt 2>&1
.venv313\Scripts\python.exe manage.py migrate > migrate_log.txt 2>&1
start "PCT Backend (Django)" cmd /k ".venv313\Scripts\python.exe manage.py runserver 127.0.0.1:8000"
