@echo off
setlocal
title The Fly Matrix - Installation Verification

echo ============================================================
echo  The Fly Matrix - verification complete de l'installation
echo ============================================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo [ERREUR] .venv est absent. Lancez setup.bat -Profile full.
  echo.
  pause
  exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -m the_fly_matrix.verify_install
set "SCRIPT_EXIT=%ERRORLEVEL%"

echo.
if "%SCRIPT_EXIT%"=="0" (
  echo [OK] Verification complete terminee avec succes.
) else (
  echo [ERREUR] Verification terminee avec le code %SCRIPT_EXIT%.
)
echo.
pause
exit /b %SCRIPT_EXIT%

