@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - central timestep convergence v1
echo TECHNICAL NUMERICAL CONSISTENCY / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv\Scripts\python.exe
  echo Run setup.bat and setup_gpu.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Filtering all 32 central pilot candidates without ranking.
echo [INFO] Comparing 5.0, 2.5 and 1.25 ms over the same 400 ms horizon.
echo [INFO] V1 ignores monotonic ordering only below the explicit 1e-4 GPU floor.
echo [INFO] Material amplitude and pattern tolerances are unchanged from v0.
echo [INFO] No body, behavior, visual choice or held-out protocol is used.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner --job calibration\runner\central-timestep-convergence-v1.yaml
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Every candidate was accounted and at least one passed.
) else (
  echo [FAILED] Constraint run failed or no candidate passed. Code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
