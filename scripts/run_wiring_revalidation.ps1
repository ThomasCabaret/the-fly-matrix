param(
    [ValidateSet("all", "input", "output")]
    [string]$Direction = "all",
    [switch]$NoOpen,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Rules = Join-Path $ProjectRoot "wiring\revalidation\rules-v1.yaml"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - revalidation scientifique du cablage" -ForegroundColor Green
    Write-Host "Projet    : $ProjectRoot"
    Write-Host "Direction : $Direction"
    Write-Host "Aucune calibration et aucune promotion automatique." -ForegroundColor Yellow

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez d'abord setup.bat."
    }
    if (-not (Test-Path -LiteralPath $Rules)) {
        throw "Jeu de regles introuvable: $Rules"
    }

    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Write-Host "`nEtapes :" -ForegroundColor Cyan
    Write-Host "  1. Relire annotations brutes et drapeaux neuronaux"
    Write-Host "  2. Reconstruire populations et groupes sans utiliser le precablage"
    Write-Host "  3. Appliquer les regles versionnees et comptabiliser chaque groupe"
    Write-Host "  4. Comparer au precablage et detecter omissions, conflits et derives"
    Write-Host "  5. Produire decisions, exceptions, blocages et rapport HTML"

    $Arguments = @(
        "-m", "the_fly_matrix.wiring_revalidation",
        "--rules", $Rules,
        "--direction", $Direction
    )
    if ($NoOpen) { $Arguments += "--no-open" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "La revalidation a termine avec le code $LASTEXITCODE. Consultez le rapport d'exceptions."
    }

    Write-Host "`n[OK] Comptabilite des regles terminee." -ForegroundColor Green
    Write-Host "Rapport : reports\generated\wiring-revalidation.html"
    Write-Host "Dernier run : data\derived\wiring-revalidation\latest.json"
    Write-Host "La revue scientifique globale reste ouverte tant que les matrices candidates fines ne sont pas reconstruites."
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
