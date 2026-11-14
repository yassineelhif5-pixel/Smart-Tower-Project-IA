@echo off
chcp 65001 >nul
title Demarrage - Project Control Tower
REM Demarre le backend Django (port 8000) et le frontend React (port 5173), puis ouvre le navigateur.
set ROOT=%~dp0..
call "%~dp04-ARRETER.bat" silent
cd /d "%ROOT%\backend"
echo Mise a jour des dependances et de la base...
.venv313\Scripts\python.exe -m pip install -q -r requirements.txt
.venv313\Scripts\python.exe manage.py migrate
start "PCT Backend (Django)" cmd /k ".venv313\Scripts\python.exe manage.py runserver 127.0.0.1:8000"
cd /d "%ROOT%\frontend"
start "PCT Frontend (Vite)" cmd /k "npm run dev"
echo Ouverture du navigateur dans 8 secondes...
timeout /t 8 /nobreak >nul
start "" http://localhost:5173
