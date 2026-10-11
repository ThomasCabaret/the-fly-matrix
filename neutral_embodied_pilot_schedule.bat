@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Neutral Embodied Pilot Schedule

echo ============================================================
echo THE FLY MATRIX - NEUTRAL EMBODIED PILOT SCHEDULE V0
echo SCHEDULE ONLY / NOT STABILITY / NO BEHAVIOR / NO SELECTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Rebuilding the exact 120-tuple factorized panel.
echo [INFO] Checking all profiles, FeCO alternatives, routes and gains.
echo [INFO] Keeping unscheduled and slow-blocked motor assignments visible.
echo [LIMIT] This command executes no physical episode and selects no candidate.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_pilot_schedule
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Exact pilot schedule compiled and validated.
  echo [SCHEDULE] calibration\schedules\neutral-embodied-stability-pilot-v0.csv
  echo [RESULT] calibration\runner\neutral-embodied-stability-pilot-schedule-v0.yaml
) else (
  echo [FAILED] Frozen inputs, coverage, balance or leakage policy failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
