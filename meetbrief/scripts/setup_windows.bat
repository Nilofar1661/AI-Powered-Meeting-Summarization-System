@echo off
setlocal
cd /d "%~dp0.."
py -3 -m venv .venv
if errorlevel 1 (
  echo Python 3.11+ was not found. Install Python and ensure the py launcher is available.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if not exist .env copy .env.example .env
echo Setup complete. Edit .env (admin password and app secret), then run scripts\start_windows.bat
pause
