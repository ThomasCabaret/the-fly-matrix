@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - signed MaleCNS technical fitting pilot
echo TRAINED TECHNICAL STABILITY / NOT PHYSIOLOGY / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat and setup_gpu.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] 32 deterministic candidates, 12 shared parameters each.
echo [INFO] Every candidate runs 3 train and 2 validation scenarios.
echo [INFO] Rejected and failed candidates remain recorded.
echo [INFO] Passing identifies a technical admissible ensemble only.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner --job calibration\runner\technical-neural-dynamics-pilot-v0.yaml
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Pilot search completed with at least one admissible candidate.
) else (
  echo [FAILED] Pilot search failed or found no admissible candidate. Code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
