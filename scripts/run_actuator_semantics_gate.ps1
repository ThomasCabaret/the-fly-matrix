param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - audit des actionneurs FlyBody" -ForegroundColor Green
    Write-Host "Projet  : $ProjectRoot"
    Write-Host "Contrat : ACTUATOR ATTRIBUTION GATE / NO CALIBRATION / NO BEHAVIOR" -ForegroundColor Yellow
    Write-Host "Portee  : 102 moteurs, reference passive, impulsion, echelon, relachement, saturation"
    Write-Host "Limite  : cette passe ne compare pas encore une boucle MaleCNS fermee."
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez setup.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    & $Python -m the_fly_matrix.actuator_semantics
    if ($LASTEXITCODE -ne 0) { throw "L'audit a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[OK] Attribution mecanique locale mesuree; le gate global reste ouvert." -ForegroundColor Green
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
