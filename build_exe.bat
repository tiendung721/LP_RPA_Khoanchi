@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "BUILD_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%BUILD_PYTHON%" (
    echo Chua tim thay moi truong ao .venv.
    echo Hay tao .venv va cai requirements-dev.txt truoc khi dong goi.
    exit /b 1
)

"%BUILD_PYTHON%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Chua cai PyInstaller. Hay chay:
    echo   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    exit /b 1
)

"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean pyinstaller.spec
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
if "%BUILD_EXIT_CODE%"=="0" (
    echo.
    echo Da tao ban dong goi trong thu muc dist.
) else (
    echo.
    echo Dong goi that bai voi ma loi %BUILD_EXIT_CODE%.
)
exit /b %BUILD_EXIT_CODE%
