@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run scripts\setup_windows.bat first.
  pause
  exit /b 1
)
set COOKIE_SECURE=false
call ".venv\Scripts\activate.bat"
python db_setup.py
if errorlevel 1 exit /b 1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
