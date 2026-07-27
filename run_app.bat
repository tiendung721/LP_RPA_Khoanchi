@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
    echo Chua tim thay moi truong ao .venv.
    echo.
    echo Hay chay cac lenh sau:
    echo   py -3.12 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install --upgrade pip
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

"%APP_PYTHON%" main.py %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo Ung dung ket thuc voi ma loi %APP_EXIT_CODE%.
)
exit /b %APP_EXIT_CODE%
