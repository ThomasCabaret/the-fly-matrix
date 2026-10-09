@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - MOTOR TWITCH TEMPORAL DIAGNOSTIC
echo ONE CELL PER CLASS / NO BEHAVIOR / NO PARAMETER PROMOTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying all three exact source archives.
echo [INFO] Selecting neutral-position single-spike traces under source rules.
echo [INFO] Fitting fast/intermediate shapes with trial-held-out folds.
echo [INFO] Slow remains unresolved if no isolated spike trial exists.
echo [INFO] No value or body-class assignment can be promoted by this run.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.motor_twitch_temporal_fit
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Temporal diagnostic completed with exhaustive accounting.
  echo [LIMIT] Results are within-cell candidate envelopes, not population calibration.
) else (
  echo [FAILED] A hash, schema, selection, fold or accounting invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
