@echo off
REM Cree un compte qa_<profil> par role, rattache aux clients/projets de test (mots de passe dans backend\qa_accounts.txt).
cd /d "%~dp0backend"
.venv313\Scripts\python.exe manage.py shell -c "exec(open('qa_setup_full.py', encoding='utf-8').read())" > qa_setup_log.txt 2>&1
