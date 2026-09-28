@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 goto failed
echo Installation complete. Open Start PCB Studio.cmd.
pause
exit /b 0
:failed
echo Installation failed. Check Python 3.11 or newer and your internet connection.
pause
exit /b 1
