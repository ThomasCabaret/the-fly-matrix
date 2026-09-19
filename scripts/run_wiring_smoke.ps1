param([switch]$NoPause)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - smoke test du cablage executable" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez d'abord setup.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Write-Host "`n[1/2] Regeneration des manifestes de cablage" -ForegroundColor Cyan
    & $Python -m the_fly_matrix.wiring
    if ($LASTEXITCODE -ne 0) { throw "La generation du cablage a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[2/2] Execution des boites et injection CNS" -ForegroundColor Cyan
    & $Python -m the_fly_matrix.wiring_smoke
    if ($LASTEXITCODE -ne 0) { throw "Le smoke test a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[OK] Cablage executable valide sans calibration." -ForegroundColor Green
}
catch {
    $ExitCode = 1
    Write-Host "`n[ECHEC] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
