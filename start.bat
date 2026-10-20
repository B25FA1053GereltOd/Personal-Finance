@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 (
    echo Cannot open the project folder. Check its location and permissions.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo Workspace Python is missing. Follow the one-time setup in README.md.
    popd
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m app
set "finance_exit=%errorlevel%"
if not "%finance_exit%"=="0" (
    echo Application exited with an error. Read the message above and check README.md.
    pause
)
popd
exit /b %finance_exit%
