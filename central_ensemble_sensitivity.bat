@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - central ensemble motor sensitivity
echo DIAGNOSTIC ONLY / NO SELECTION / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat and setup_gpu.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Comparing all 32 technically admissible central candidates.
echo [INFO] Each candidate receives 3 paired stimulus-versus-sham probes.
echo [INFO] Responses are read only at the 815 raw MaleCNS motor terminals.
echo [INFO] Motor transfer, body physics and behavior are not executed.
echo [INFO] This run measures dispersion; it cannot select a candidate.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner --job calibration\runner\central-ensemble-motor-sensitivity-v0.yaml
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Complete ensemble sensitivity was measured and recorded.
) else (
  echo [FAILED] Sensitivity measurement failed. Code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
