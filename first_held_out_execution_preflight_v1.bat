@echo off
setlocal
cd /d "%~dp0"
echo [FH-09 V1] Materialisation et verification sans lecture de resultat held-out...
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_execution_preflight ^
  --campaign calibration\campaigns\first-held-out-execution-preflight-v1.yaml ^
  --result calibration\runner\first-held-out-execution-preflight-v1.yaml ^
  --evaluation calibration\evaluations\first-held-out-execution-preflight-v1.yaml ^
  --output-root data\derived\calibration\first-held-out-execution-preflight-v1
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [FH-09 V1] Preflight termine. Zero outcome held-out execute.
) else (
  echo [FH-09 V1] ECHEC du preflight ^(code %TFM_EXIT%^). Aucun outcome ne doit etre execute.
)
echo.
pause
exit /b %TFM_EXIT%
