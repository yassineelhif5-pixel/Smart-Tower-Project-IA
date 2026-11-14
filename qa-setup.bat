@echo off
REM Crée / réinitialise les comptes de recette qa_pilote et qa_admin (mots de passe dans backend\qa_accounts.txt).
cd /d "%~dp0backend"
.venv313\Scripts\python.exe manage.py shell < qa_setup.py > qa_setup_log.txt 2>&1
