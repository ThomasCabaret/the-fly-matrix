@echo off
setlocal
cd /d "%~dp0"
echo [FH-09] Materialisation et verification sans lecture de resultat held-out...
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_execution_preflight
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [FH-09] Preflight termine. Consultez calibration\runner\first-held-out-execution-preflight-v0.yaml
) else (
  echo [FH-09] ECHEC du preflight ^(code %TFM_EXIT%^). Aucun resultat comportemental ne doit etre execute.
)
echo.
pause
exit /b %TFM_EXIT%
