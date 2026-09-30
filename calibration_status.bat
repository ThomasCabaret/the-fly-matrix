@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - CALIBRATION INVENTORY STATUS
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERREUR] Environnement Python absent.
  echo Lancez setup.bat avant ce script.
  set "EXIT_CODE=1"
  goto :finish
)

echo Validation des familles, de leur comptabilite et du DAG...
echo.
".venv\Scripts\python.exe" -m the_fly_matrix calibration-status
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [TERMINE] Le registre de calibration est structurellement coherent.
) else (
  echo [ECHEC] Le registre de calibration contient une incoherence.
)
echo Code de sortie : %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
