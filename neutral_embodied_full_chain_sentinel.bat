@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - FULL LOCAL-CHAIN EXECUTION SENTINEL
echo  Diagnostic candidates only - not calibration or stability
echo ============================================================
echo.
echo Executing FeCO -^> typed local CNS -^> motor -^> MuJoCo...
echo Heavy episode arrays will stay under ignored runs/calibration/.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_full_chain_sentinel
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Full local-chain execution sentinel passed.
) else (
  echo [FAILED] Sentinel stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
