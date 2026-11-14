@echo off
chcp 65001 >nul
title Installation - Project Control Tower
REM A lancer UNE FOIS (ou apres une mise a jour des dependances).
set ROOT=%~dp0..
echo [1/3] Environnement Python...
cd /d "%ROOT%\backend"
if not exist .venv313\Scripts\python.exe (py -3.13 -m venv .venv313 || python -m venv .venv313)
.venv313\Scripts\python.exe -m pip install --upgrade pip
.venv313\Scripts\python.exe -m pip install -r requirements.txt
echo [2/3] Base de donnees : migrations...
.venv313\Scripts\python.exe manage.py migrate
echo [3/3] Dependances du frontend (npm)...
cd /d "%ROOT%\frontend"
call npm install
echo.
echo Installation terminee. Lancez maintenant 2-DEMARRER.bat
pause
