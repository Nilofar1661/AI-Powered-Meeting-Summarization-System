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
python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
