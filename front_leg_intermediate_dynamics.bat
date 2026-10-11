@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title The Fly Matrix - Front-Leg Intermediate Dynamics Accounting

echo ============================================================
echo THE FLY MATRIX - INTERMEDIATE POPULATION ACCOUNTING
echo RULES + EXCEPTIONS / ZERO VALUES / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Applying evidence rules to all 150 bounded CNS intermediates.
echo [INFO] Joining the frozen transmitter prior for audit only.
echo [INFO] Reporting every unresolved case and evidence-acquisition priority.
echo [LIMIT] This command selects no path, value, movement or behavior.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_intermediate_dynamics
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Every scoped intermediate has one explicit disposition.
  echo [RESULT] calibration\runner\front-leg-intermediate-dynamics-accounting-v0.yaml
) else (
  echo [FAILED] A frozen input, rule, count or exposure invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
