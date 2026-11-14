@echo off
REM Applique les migrations Django sur la base (DATABASE_URL du fichier backend\.env). Résultat dans backend\migrate_log.txt
cd /d "%~dp0backend"
.venv313\Scripts\python.exe manage.py migrate > migrate_log.txt 2>&1
type migrate_log.txt
echo.
pause
