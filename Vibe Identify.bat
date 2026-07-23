@echo off
REM ===================================================================
REM  Vibe Identify - launch the native desktop shell (no browser, no WSL).
REM  Double-click this file. It runs the desktop shell with the project
REM  venv's pythonw.exe, so the same interpreter hosts the window and the
REM  backend (native ONNX engine). A console may flash for a split second.
REM ===================================================================
cd /d "%~dp0"

set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
set "SHELL=%~dp0desktop\genre_app.pyw"

if exist "%VENV_PYW%" (
    REM start "" detaches so this window closes immediately; pythonw = no console.
    start "" "%VENV_PYW%" "%SHELL%"
    goto :eof
)

echo(
echo   Project venv not found at:
echo     %VENV_PYW%
echo(
echo   Create it and install the runtime + shell deps, then re-run:
echo     py -m venv .venv
echo     .venv\Scripts\python -m pip install -r requirements.txt
echo     .venv\Scripts\python -m pip install -r desktop\requirements-desktop.txt
echo(
pause
