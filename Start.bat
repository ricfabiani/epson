@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
    goto install
)
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 goto missing
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --require-hashes -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m epson_reset %*
if errorlevel 1 goto failed
exit /b 0
:missing
echo Install Python 3.11 or newer from https://www.python.org/downloads/windows/
echo Include Tcl/Tk and the Python launcher during installation, then run Start.bat again.
pause
exit /b 1
:failed
echo The app could not start. Read the error above for details.
pause
exit /b 1
