@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - MOTOR SPIKE/FORCE AGGREGATE PILOT FIT
echo ONE CELL PER CLASS / NO KERNEL / NO BEHAVIOR / NO PROMOTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Checking the three exact source archive identities.
echo [INFO] Requiring a versioned raw-MAT to normalized-table parser manifest.
echo [INFO] Slow reproduces the sourced zero-intercept fit form.
echo [INFO] Fast/intermediate fits are diagnostic extensions, not source claims.
echo [INFO] One cell per class cannot promote population or body parameters.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.motor_spike_force_fit
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Three aggregate diagnostic fits completed; zero values promoted.
  echo [LIMIT] No population distribution, body crosswalk or twitch kernel was identified.
) else if "%EXIT_CODE%"=="2" (
  echo [BLOCKED] Exact archives and a versioned raw-variable parser are required.
  echo [NEXT] Run prepare_local_source_data.bat --include-large-motor-pilot, then inspect_motor_pilot.bat.
) else (
  echo [FAILED] A schema, hash, unit, class, filter or accounting invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
