@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo The Fly Matrix - central timestep convergence constraint
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
echo [INFO] Three stimulus-versus-sham probes cover the full CNS and 815 motor outputs.
echo [INFO] No body, behavior, visual choice or held-out protocol is used.
echo [INFO] A zero-pass result is retained; thresholds will not be relaxed automatically.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.calibration_runner --job calibration\runner\central-timestep-convergence-v0.yaml
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
