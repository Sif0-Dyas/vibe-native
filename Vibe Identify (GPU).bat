@echo off
REM ===================================================================
REM  Vibe Identify - GPU (DirectML) mode.  NOT RECOMMENDED right now.
REM
REM  The normal launcher runs on CPU, which is the default because the
REM  DirectML path faults inside the NVIDIA D3D driver part-way through
REM  a large batch scan (0xc0000005 in nvwgf2umx.dll, same fault offset
REM  every time). That kills the whole app mid-scan and cannot be caught
REM  or recovered from in Python.
REM
REM  Measured cost of staying on CPU, same models and weights:
REM      2.8-minute track   GPU 1.96s   CPU 2.04s   (+4%)
REM      8.4-minute track   GPU 5.54s   CPU 5.91s   (+7%)
REM
REM  Use this launcher to re-test the GPU after an NVIDIA driver update.
REM ===================================================================
cd /d "%~dp0"

set "VIBE_PROVIDER=gpu"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
set "SHELL=%~dp0desktop\genre_app.pyw"

if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%SHELL%"
    goto :eof
)

echo(
echo   Project venv not found at:
echo     %VENV_PYW%
echo(
pause
