@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - one-time held-out protocol v2 execution
echo ============================================================
echo [WARNING] This exposes the locked held-out outcomes.
echo [WARNING] It never calibrates, ranks or changes parameters.
echo [INFO] Complete shards are append-only and safely resumable.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Run setup.bat first.
  goto :end
)
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_execution
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] Held-out v2 execution and report completed.
) else (
  echo [ERROR] Execution stopped with exit code %EXIT_CODE%.
  echo [INFO] Run this file again to resume complete append-only shards.
)
:end
echo.
pause
exit /b %EXIT_CODE%

