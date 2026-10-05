param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - attribution causale des actionneurs FlyBody" -ForegroundColor Green
    Write-Host "Projet  : $ProjectRoot"
    Write-Host "Contrat : DIAGNOSTIC ONLY / ZERO OPTIMIZATION / NO BEHAVIOR" -ForegroundColor Yellow
    Write-Host "Portee  : mecanique passive, commandes gelees en boucle ouverte, feedback MaleCNS"
    Write-Host "Fixture : 102 moteurs tethered sans sol pour la symetrie intrinseque"
    Write-Host "Sortie  : resultat compact versionne et traces lourdes ignorees par Git"
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez setup.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    & $Python -m the_fly_matrix.actuator_attribution
    if ($LASTEXITCODE -ne 0) {
        throw "L'attribution causale a echoue avec le code $LASTEXITCODE."
    }
    Write-Host "`n[OK] Gate causal ferme comme surrogate direct-motor borne." -ForegroundColor Green
    Write-Host "[LIMITE] Ce resultat ne valide ni les muscles, ni MaleCNS, ni un comportement." -ForegroundColor Yellow
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
