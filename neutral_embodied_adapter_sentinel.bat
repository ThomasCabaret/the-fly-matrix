@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Neutral Embodied Adapter Sentinel

echo ============================================================
echo THE FLY MATRIX - NEUTRAL EMBODIED ADAPTER SENTINEL V0
echo SYNTHETIC MOTOR EVENT / NOT FULL CHAIN / NOT STABILITY
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying the immutable 120-tuple schedule and fixed sentinel IDs.
echo [INFO] Compiling four motor event-to-force-to-command traces.
echo [INFO] Running eight paired baseline/perturbed MuJoCo episodes.
echo [LIMIT] FeCO and intermediate-CNS axes are loaded but not executed.
echo [LIMIT] Physical motion selects no candidate and establishes no stability.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_adapter_sentinel
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Motor-to-physics adapter sentinel completed.
  echo [RESULT] calibration\runner\neutral-embodied-adapter-sentinel-v0.yaml
  echo [NEXT] Instantiate FeCO-to-CNS and typed intermediate execution before the full panel.
) else (
  echo [FAILED] A schedule, compiler, pairing or physical execution invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
