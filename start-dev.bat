@echo off
REM Lance le backend Django (port 8000) et le frontend React (port 5173).
cd /d "%~dp0backend"
start "PCT Backend (Django)" cmd /k ".venv313\Scripts\python.exe manage.py check --database default && .venv313\Scripts\python.exe manage.py runserver 127.0.0.1:8000"
cd /d "%~dp0frontend"
start "PCT Frontend (Vite)" cmd /k "npm run dev"
