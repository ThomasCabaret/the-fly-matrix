@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - FRONT-LEG LOCAL CONVERSION CONTRACT
echo STRUCTURAL PROBE / ZERO FITTED VALUES / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Checking frozen proprioception and motor topology hashes.
echo [INFO] Exercising both FeCO native-output candidates without selecting one.
echo [INFO] Exercising motor events to biological force, then force to MuJoCo command.
echo [INFO] Synthetic constants are structural test fixtures only; none are calibrated.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.local_conversion
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Local conversion contracts passed.
  echo [NEXT] Biological values and population crosswalks remain unresolved.
) else (
  echo [FAILED] A local conversion invariant or frozen boundary failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
