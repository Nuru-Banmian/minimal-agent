@echo off
setlocal
chcp 65001 >nul

pushd "%~dp0"
if errorlevel 1 (
    echo Cannot open the project directory.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Python virtual environment not found. Run these commands in the project directory:
    echo py -3.13 -m venv .venv
    echo .venv\Scripts\python.exe -m pip install -e ".[dev]"
    pause
    popd
    exit /b 1
)

".venv\Scripts\python.exe" -X utf8 -m minimal_agent
set "app_exit=%errorlevel%"
if not "%app_exit%"=="0" pause
popd
exit /b %app_exit%
