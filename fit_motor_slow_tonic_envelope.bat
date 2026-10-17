@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  The Fly Matrix - enveloppe tonique du moteur lent
echo ============================================================
echo.
echo [INFO] Analyse locale multi-spike; aucun mouvement ni comportement.
echo [INFO] Aucun parametre ni bodyId/classe ne sera promu.
echo.

.\.venv\Scripts\python.exe -m the_fly_matrix.motor_slow_tonic_envelope
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] L'enveloppe diagnostique lente a ete reconstruite.
) else (
  echo [ECHEC] La campagne s'est arretee avec le code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
