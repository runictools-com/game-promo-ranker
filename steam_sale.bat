@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
set "SCRIPT=%~dp0steam_sale_ranker.py"

if "%1"=="" (
    "%PYTHON%" "%SCRIPT%" 10
) else (
    "%PYTHON%" "%SCRIPT%" %*
)

pause
