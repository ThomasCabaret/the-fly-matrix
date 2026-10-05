@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - isolated Brian2 2.5.1 reference runtime
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup_brian2_reference.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Reference environment is ready under runs\reference-env.
) else (
  echo [ERROR] Setup failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
