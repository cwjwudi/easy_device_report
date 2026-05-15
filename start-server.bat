@echo off
cd /d %~dp0
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m http.server --bind 0.0.0.0 8000
pause
