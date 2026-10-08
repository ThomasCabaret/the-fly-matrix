param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - contrat de metriques de stabilite incarnee" -ForegroundColor Green
    Write-Host "Projet  : $ProjectRoot"
    Write-Host "Contrat : DIAGNOSTIC ONLY / ZERO OPTIMIZATION / NO BEHAVIOR" -ForegroundColor Yellow
    Write-Host "Entree  : replay physique non calibre, gele par SHA-256"
    Write-Host "Mesures : temps, numerique, CNS, racine, articulations, contacts, commandes"
    Write-Host "Limite  : aucun seuil de stabilite n'est choisi ou accepte dans ce lot" -ForegroundColor Yellow
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez setup.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    & $Python -m the_fly_matrix.embodied_stability_metrics
    if ($LASTEXITCODE -ne 0) {
        throw "La mesure a echoue avec le code $LASTEXITCODE."
    }
    Write-Host "`n[OK] Contrat de mesure execute." -ForegroundColor Green
    Write-Host "[LIMITE] Le resultat decrit le replay; il ne prouve pas une mouche stable." -ForegroundColor Yellow
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
