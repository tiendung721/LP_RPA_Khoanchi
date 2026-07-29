@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0" || goto :root_error

set "APP_ROOT=%CD%"
set "VENV_DIR=%APP_ROOT%\.venv"
set "APP_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS_FILE=%APP_ROOT%\requirements.txt"
set "REQUIREMENTS_MARKER=%VENV_DIR%\.requirements.sha256"

if not exist "%APP_ROOT%\main.py" goto :missing_files
if not exist "%REQUIREMENTS_FILE%" goto :missing_files
if exist "%APP_PYTHON%" goto :validate_venv

echo [1/3] Dang tao moi truong Python .venv...
where py >nul 2>&1
if errorlevel 1 goto :try_python_command
py -3.12 -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto :try_python_command
py -3.12 -m venv "%VENV_DIR%"
if errorlevel 1 goto :venv_create_error
goto :validate_venv

:try_python_command
where python >nul 2>&1
if errorlevel 1 goto :python_missing
python -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto :python_missing
python -m venv "%VENV_DIR%"
if errorlevel 1 goto :venv_create_error

:validate_venv
if not exist "%APP_PYTHON%" goto :venv_create_error
"%APP_PYTHON%" -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto :venv_invalid

"%APP_PYTHON%" -c "import hashlib, pathlib, sys; requirement = pathlib.Path(sys.argv[1]); marker = pathlib.Path(sys.argv[2]); digest = hashlib.sha256(requirement.read_bytes()).hexdigest(); raise SystemExit(0 if marker.is_file() and marker.read_text(encoding='ascii').strip() == digest else 1)" "%REQUIREMENTS_FILE%" "%REQUIREMENTS_MARKER%" >nul 2>&1
if errorlevel 1 goto :install_dependencies

"%APP_PYTHON%" -c "import PySide6, openpyxl, watchdog" >nul 2>&1
if errorlevel 1 goto :install_dependencies
goto :verify_dependencies

:install_dependencies
echo [2/3] Dang dong bo thu vien trong .venv...
"%APP_PYTHON%" -m pip install --disable-pip-version-check -r "%REQUIREMENTS_FILE%"
if errorlevel 1 goto :dependency_error
"%APP_PYTHON%" -c "import hashlib, pathlib, sys; requirement = pathlib.Path(sys.argv[1]); marker = pathlib.Path(sys.argv[2]); marker.write_text(hashlib.sha256(requirement.read_bytes()).hexdigest(), encoding='ascii')" "%REQUIREMENTS_FILE%" "%REQUIREMENTS_MARKER%"
if errorlevel 1 goto :dependency_error

:verify_dependencies
"%APP_PYTHON%" -m pip check >nul
if errorlevel 1 goto :dependency_error
"%APP_PYTHON%" -c "import PySide6, openpyxl, watchdog" >nul 2>&1
if errorlevel 1 goto :dependency_error

echo [3/3] Dang khoi dong ung dung...
"%APP_PYTHON%" "%APP_ROOT%\main.py" %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
if "%APP_EXIT_CODE%"=="0" exit /b 0

echo.
echo Ung dung ket thuc voi ma loi %APP_EXIT_CODE%.
exit /b %APP_EXIT_CODE%

:root_error
echo Khong the mo thu muc chua run_app.bat.
exit /b 1

:missing_files
echo Khong tim thay main.py hoac requirements.txt can thiet de chay ung dung.
exit /b 1

:python_missing
echo Khong tim thay Python 3.12 64-bit.
echo Hay cai Python 3.12 64-bit, sau do chay lai run_app.bat.
exit /b 1

:venv_create_error
echo Khong the tao moi truong .venv.
echo Kiem tra quyen ghi thu muc du an va ban cai Python 3.12 64-bit.
exit /b 1

:venv_invalid
echo Moi truong .venv khong dung Python 3.12 64-bit hoac da bi hong.
echo Hay doi ten hoac xoa rieng thu muc .venv, sau do chay lai run_app.bat.
exit /b 1

:dependency_error
echo.
echo Khong the cai dat hoac kiem tra thu vien trong .venv.
echo Kiem tra ket noi mang va noi dung requirements.txt, sau do chay lai.
exit /b 1
