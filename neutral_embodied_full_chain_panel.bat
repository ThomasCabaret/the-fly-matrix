@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - IMMUTABLE 120-TUPLE LOCAL-CHAIN PANEL
echo  Diagnostic candidates only - not calibration or stability
echo ============================================================
echo.
echo Executing 120 fixed tuples and 240 paired MuJoCo episodes.
echo Every tuple and failure will be accounted. Heavy arrays stay
echo under ignored runs/calibration/. No body motion selects a candidate.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_full_chain_panel
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Immutable local-chain panel completed its execution contract.
) else (
  echo [FAILED] Panel stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
