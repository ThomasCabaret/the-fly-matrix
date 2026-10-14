@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - BASAL POPULATION REACHABILITY ACCOUNTING
echo ============================================================
echo This computes exact directed reachability and typed/hybrid
echo dispositions. It fits no values and exposes no behavior.
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.basal_population_reachability
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Basal population accounting artifacts were regenerated.
) else (
  echo [FAILED] Basal population accounting stopped with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
