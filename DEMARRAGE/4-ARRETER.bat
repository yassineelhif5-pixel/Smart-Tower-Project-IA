@echo off
REM Arrete le backend (8000) et le frontend (5173).
for %%P in (8000 5173) do for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%%P" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq PCT Backend (Django)*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq PCT Frontend (Vite)*" >nul 2>&1
if not "%1"=="silent" (echo Project Control Tower arrete. & pause)
