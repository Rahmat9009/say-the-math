@echo off
rem Say the Math launcher for Windows. Safe for folders with spaces or parentheses in their path.
rem First run: installs into .venv and node_modules and downloads the verified model (needs internet).
rem Later runs: start the local server on 127.0.0.1 and open the browser (no internet needed).
rem   Start-Windows.cmd          start (running setup first if needed)
rem   Start-Windows.cmd setup    run or repair setup, then start
setlocal EnableExtensions
cd /d "%~dp0"
if /i "%~1"=="setup" goto setup
if not exist ".venv\Scripts\python.exe" goto setup
if not exist "models\setup-record.json" goto setup
if not exist "node_modules\speech-rule-engine\package.json" goto setup
goto run

:setup
echo Setting up Say the Math. This downloads about 1 GB of packages and a 120 MB model, once.
set "SETUP_PY="
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 set "SETUP_PY=py -3.12"
if defined SETUP_PY goto do_setup
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 set "SETUP_PY=py -3.11"
if defined SETUP_PY goto do_setup
:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
set "SETUP_PY=python"
:do_setup
%SETUP_PY% "setup_app.py"
if errorlevel 1 goto setup_failed
goto run

:no_python
echo.
echo Python 3.12 or 3.11 (64-bit) was not found. Install it from https://www.python.org/downloads/
echo and Node.js 22 or newer from https://nodejs.org/, then run Start-Windows.cmd again.
pause
exit /b 1

:setup_failed
echo.
echo Setup did not finish. Read the messages above, fix the problem, then run Start-Windows.cmd setup.
pause
exit /b 1

:run
echo Starting Say the Math. Keep this window open while you use the app; close it to stop.
".venv\Scripts\python.exe" "app.py" --open
if errorlevel 1 pause
exit /b 0
