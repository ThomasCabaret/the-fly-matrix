param(
    [switch]$NoOpen,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$NodeIndex = Join-Path $ProjectRoot "data\derived\wiring\central-node-index.parquet"
$Weights = Join-Path $ProjectRoot "data\raw\malecns\v1.0\connectome-weights-male-cns-v1.0-minconf-0.5.feather"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - topologie cyclique MaleCNS" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    Write-Host "Analyse structurelle uniquement - aucune calibration" -ForegroundColor Yellow

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez d'abord setup.bat."
    }
    if (-not (Test-Path -LiteralPath $NodeIndex)) {
        throw "Index neuronal absent. Lancez d'abord run_analysis.bat."
    }
    if (-not (Test-Path -LiteralPath $Weights)) {
        throw "Table des connexions MaleCNS absente. Lancez d'abord download_data.bat."
    }

    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Write-Host "`nEtapes :" -ForegroundColor Cyan
    Write-Host "  1. Construire ou reutiliser l'adjacence topologique locale"
    Write-Host "  2. Parcourir les generations depuis les 17 884 entrees"
    Write-Host "  3. Calculer les composantes fortement connexes exactes"
    Write-Host "  4. Mesurer les retours de generation et cycles BFS exacts"
    Write-Host "  5. Produire le rapport HTML et le resume JSON"
    Write-Host "`nLe premier lancement lit deux fois le fichier d'aretes (~1 Go)."
    Write-Host "Les suivants reutilisent un cache CSR sous data\derived\analysis."

    $Arguments = @("-m", "the_fly_matrix.connectome_topology")
    if ($NoOpen) { $Arguments += "--no-open" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "L'analyse a echoue avec le code $LASTEXITCODE."
    }

    Write-Host "`n[OK] Analyse terminee." -ForegroundColor Green
    Write-Host "Rapport : reports\generated\connectome-cycle-topology.html"
    Write-Host "Donnees  : data\derived\analysis\cycle-topology\summary.json"
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
