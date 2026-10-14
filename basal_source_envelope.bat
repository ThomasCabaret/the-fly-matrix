@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo The Fly Matrix - basal source technical envelope propagation
echo 39 unranked runs; no physiology and no behavior promotion
echo ============================================================
echo.
call .venv\Scripts\python.exe -m the_fly_matrix.basal_source_envelope
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] The finite technical envelope passed all gates.
) else (
  echo [FAILED] Envelope propagation exited with code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
