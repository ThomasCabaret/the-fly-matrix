@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - unfitted signed MaleCNS characterization
echo DIAGNOSTIC ONLY / NOT CALIBRATION / NO PARAMETER PROMOTION
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat and setup_gpu.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Seven preregistered regimes will run on the full canonical graph.
echo [INFO] Each regime executes 40 steps over 166,700 neurons and 25,582,938 edges.
echo [INFO] Silence, activity, saturation and perturbation metrics are all retained.
echo [INFO] Passing means the diagnostics executed correctly, not that a regime is good.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner --job calibration\runner\central-unfitted-characterization-v0.yaml
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] All unfitted regimes were measured and accounted for.
) else (
  echo [FAILED] Unfitted characterization failed with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
