@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - BASAL READINESS AND SENSITIVITY DESIGN
echo ============================================================
echo This compiles zero physiological values and exposes blockers.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.basal_low_capacity_readiness
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Basal readiness artifacts were regenerated.
) else (
  echo [FAILED] Basal readiness stopped with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
