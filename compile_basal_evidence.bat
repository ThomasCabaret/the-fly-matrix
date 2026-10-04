@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - BASAL SOURCE EVIDENCE READINESS
echo EVIDENCE COVERAGE ONLY / ZERO PARAMETER VALUES / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] This pass accounts for all 2,212 basal source channels.
echo [INFO] It validates evidence partitions, source hashes and unit readiness.
echo [INFO] It deliberately emits no basal rate while the biological-rate
echo [INFO] to normalized-model-activity bridge remains undefined.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.basal_evidence
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] Basal evidence accounting completed successfully.
) else (
  echo [FAILED] Basal evidence accounting did not satisfy its contract.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
