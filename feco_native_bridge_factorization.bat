@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - FECO NATIVE-BRIDGE FACTORIZATION
echo LOCAL SHAPE FREEZE / NATIVE VALUES DEFERRED / NO BEHAVIOR
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying the frozen FH-03 parent and source-table hashes.
echo [INFO] Building dimensionless activation coordinates on admitted support.
echo [INFO] Materializing all 8 class-shared event/graded profiles.
echo [INFO] Native baseline and dynamic range remain explicit FH-05 unknowns.
echo [INFO] No body motion, threshold crossing, or held-out response is read.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.feco_native_bridge
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] FH-03 locally identifiable sensory components are frozen.
  echo [OPEN] Native amplitude remains a named coupled dependency of FH-05.
) else (
  echo [FAILED] A source, support, factorization, or exposure invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
