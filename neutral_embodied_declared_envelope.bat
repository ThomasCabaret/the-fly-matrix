@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - DECLARED LOCAL-CHAIN PARAMETER ENVELOPE
echo  No fit, no selection, no physical stability claim
echo ============================================================
echo.
echo Rebuilding balanced FeCO-routing and unknown-sign panels,
echo the bounded numeric profiles, and the exact execution schedule.
echo No physical trajectory or named behavior is inspected.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_declared_envelope
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Declared candidate envelope and schedule are valid.
) else (
  echo [FAILED] Envelope compilation stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
