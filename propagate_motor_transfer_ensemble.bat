@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - propagation de l'ensemble moteur T1
echo ============================================================
echo [INFO] Verifie les preuves verrouillees et les 59 049 affectations.
echo [INFO] Aucun comportement, mouvement ou parametre n'est selectionne.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.motor_transfer_propagation
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [SUCCES] Ensemble moteur factorise compile et valide.
) else (
  echo [ECHEC] La propagation a echoue avec le code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
