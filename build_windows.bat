@echo off
setlocal

cd /d "%~dp0"

set "APP_NAME=DailyTodo"
set "APP_VERSION=%~1"
set "BUILD_TYPE=%~2"
if "%APP_VERSION%"=="" set "APP_VERSION=0.0.0"
if "%BUILD_TYPE%"=="" set "BUILD_TYPE=dev"
if /I "%BUILD_TYPE%"=="development" set "BUILD_TYPE=dev"
if /I "%BUILD_TYPE%"=="debug" set "BUILD_TYPE=dev"
if /I "%BUILD_TYPE%"=="prod" set "BUILD_TYPE=release"
if /I "%BUILD_TYPE%"=="production" set "BUILD_TYPE=release"
if /I not "%BUILD_TYPE%"=="dev" if /I not "%BUILD_TYPE%"=="release" (
    echo Usage: build_windows.bat [version] [dev^|release]
    exit /b 2
)
set "PYTHON=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\pip.exe"
set "DEPLOY=.venv\Scripts\pyside6-deploy.exe"
set "DIST_DIR=dist"
set "APP_DIST=deployment\main.dist"
set "PACKAGE_ROOT=%DIST_DIR%\package"
set "PACKAGE_DIR=%PACKAGE_ROOT%\%APP_NAME%"
set "ZIP_PATH=%DIST_DIR%\%APP_NAME%-%APP_VERSION%-%BUILD_TYPE%-windows.zip"

if not exist "%PYTHON%" (
    echo [DailyTodo] Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
)

echo [DailyTodo] Installing dependencies...
"%PIP%" install -r requirements.txt
if errorlevel 1 exit /b 1

echo [DailyTodo] Building translations...
"%PYTHON%" tools\build_translations.py
if errorlevel 1 exit /b 1

echo [DailyTodo] Writing pyside6-deploy spec for %BUILD_TYPE% %APP_VERSION%...
"%PYTHON%" tools\write_deploy_spec.py --version "%APP_VERSION%" --build-type "%BUILD_TYPE%"
if errorlevel 1 exit /b 1

echo [DailyTodo] Building Windows standalone directory with pyside6-deploy...
"%DEPLOY%" -c pysidedeploy.spec --name "%APP_NAME%" --force --keep-deployment-files
if errorlevel 1 exit /b 1

if not exist "%APP_DIST%" (
    echo [DailyTodo] Build output not found: %APP_DIST%
    exit /b 1
)

if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if exist "%PACKAGE_ROOT%" rmdir /s /q "%PACKAGE_ROOT%"
mkdir "%PACKAGE_DIR%"
xcopy "%APP_DIST%\*" "%PACKAGE_DIR%\" /E /I /Y >nul
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%"

echo [DailyTodo] Creating zip package: %ZIP_PATH%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%PACKAGE_DIR%' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 exit /b 1

echo [DailyTodo] Windows package completed: %ZIP_PATH%
echo [DailyTodo] Run executable from extracted package: DailyTodo\main.exe
endlocal
