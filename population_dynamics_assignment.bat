@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - FRONT-LEG POPULATION DYNAMICS ASSIGNMENT
echo EVIDENCE ACCOUNTING / ZERO VALUES / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Auditing 36 front-leg FeCO afferents and 10 T1 tibia-flexor motor neurons.
echo [INFO] The pass may assign event, graded, dual_unresolved or excluded.
echo [INFO] It does not fit neural, sensory, motor or physical parameter values.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.population_dynamics_assignment
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Population assignment accounting completed successfully.
) else (
  echo [FAILED] Population assignment accounting did not satisfy its contract.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
