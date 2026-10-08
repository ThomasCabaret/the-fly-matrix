@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - MOTOR SPIKE/FORCE SOURCE CONTRACT
echo PINNED PUBLIC CODE / ZERO FIT / ZERO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying five checksum-locked Zenodo source files.
echo [INFO] Reconstructing all 23 source cells and the 194 selected pilot trials.
echo [INFO] Locking filters, duration and probe-calibration unit transforms.
echo [INFO] No raw archive, behavior, body crosswalk or parameter is fitted.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.motor_source_contract
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Source cohort and aggregate spike/force rules are reproducible.
  echo [LIMIT] Raw variable schema and temporal twitch kernel remain unresolved.
) else (
  echo [FAILED] A source hash, cohort, unit, filter or scope invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
