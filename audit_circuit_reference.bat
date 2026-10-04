@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo ============================================================
echo The Fly Matrix - audit de transferabilite du circuit de reference
echo ============================================================
echo.
echo Ce script ne calibre rien et ne valide aucun comportement.
echo Il verifie les identites FlyWire/MaleCNS et les chemins structuraux.
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERREUR] Environnement Python absent. Lancez setup.bat.
  goto :finish
)

".venv\Scripts\python.exe" -m the_fly_matrix.circuit_reference_audit
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Audit termine. Consultez calibration\runner\antennal-grooming-circuit-transferability-result-v0.yaml
) else (
  echo [ERREUR] Audit interrompu avec le code %EXIT_CODE%.
)

:finish
echo.
pause
endlocal
