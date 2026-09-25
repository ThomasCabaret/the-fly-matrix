param(
    [double]$Duration = 0,
    [int]$Seed = 260925,
    [double]$Amplitude = 0.003,
    [double]$Speed = 1.0,
    [double]$PhysicsTimestep = 0.0005,
    [int]$ControlSubsteps = 20,
    [double]$RenderFps = 30,
    [switch]$Headless,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ActuatorManifest = Join-Path $ProjectRoot "data\derived\wiring\flybody-actuator-channels.csv"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - DIAGNOSTIC physical viewer" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host " NOT MALECNS - NOT CALIBRATION - NOT A SCIENTIFIC BEHAVIOR" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "This viewer uses an isolated seeded toy recurrent controller." -ForegroundColor Yellow
    Write-Host "It bypasses the real connectome and scientific motor mapping." -ForegroundColor Yellow

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez d'abord setup.bat -Profile body."
    }
    if (-not (Test-Path -LiteralPath $ActuatorManifest)) {
        throw "Manifeste des actionneurs absent. Lancez d'abord run_analysis.bat."
    }

    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Write-Host "`n[1/2] Configuration" -ForegroundColor Cyan
    Write-Host "Seed               : $Seed"
    Write-Host "Amplitude maximale : $Amplitude"
    Write-Host "Vitesse cible      : ${Speed}x (0 = sans limitation)"
    Write-Host "Pas physique       : $PhysicsTimestep s (profil viewer; natif = 0.0001)"
    Write-Host "Sous-pas/commande  : $ControlSubsteps"
    Write-Host "Rafraichissement   : $RenderFps FPS"
    if ($Duration -eq 0) {
        Write-Host "Duree              : jusqu'a fermeture de la fenetre"
    } else {
        Write-Host "Duree simulee      : $Duration s"
    }
    Write-Host "Mode                : $(if ($Headless) { 'headless' } else { 'viewer interactif' })"

    if (-not $Headless) {
        Write-Host "`nControles dans la fenetre MuJoCo :" -ForegroundColor Cyan
        Write-Host "  Souris gauche + glisser : tourner autour de la scene"
        Write-Host "  Souris droite + glisser : deplacer la vue"
        Write-Host "  Molette                 : zoomer/dezoomer"
        Write-Host "  Espace                   : pause/reprise"
        Write-Host "  R ou Retour arriere      : reinitialiser"
        Write-Host "  Q ou Echap               : quitter"
    }

    Write-Host "`n[2/2] Lancement du moteur physique" -ForegroundColor Cyan
    $Arguments = @(
        "-m", "the_fly_matrix.diagnostics.viewer_demo",
        "--duration", $Duration,
        "--seed", $Seed,
        "--amplitude", $Amplitude,
        "--speed", $Speed,
        "--physics-timestep", $PhysicsTimestep,
        "--control-substeps", $ControlSubsteps,
        "--render-fps", $RenderFps
    )
    if ($Headless) { $Arguments += "--headless" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "La demonstration diagnostique a echoue avec le code $LASTEXITCODE."
    }
    Write-Host "`n[OK] Demonstration terminee proprement." -ForegroundColor Green
    Write-Host "Resume : runs\diagnostic-viewer\latest.json"
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
