param([switch]$NoPause)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements-gpu-cu126.txt"
$ExitCode = 0

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

try {
    Write-Host "The Fly Matrix - CUDA environment setup" -ForegroundColor Green
    Write-Host "Project      : $ProjectRoot"
    Write-Host "Environment  : $Python"
    Write-Host "Requirements : $Requirements"

    if (-not (Test-Path -LiteralPath $Python)) {
        throw ".venv est absent. Lancez d'abord setup.bat -Profile full."
    }
    if (-not (Test-Path -LiteralPath $Requirements)) {
        throw "Fichier de dependances GPU absent: $Requirements"
    }

    Write-Step "Inventaire du pilote et du GPU"
    $NvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $NvidiaSmi) { throw "nvidia-smi.exe est introuvable." }
    & $NvidiaSmi.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi a echoue." }

    Write-Step "Installation de PyTorch CUDA 12.6"
    Write-Host "Le telechargement peut etre volumineux et prendre plusieurs minutes."
    & $Python -m pip install --requirement $Requirements
    if ($LASTEXITCODE -ne 0) { throw "L'installation de PyTorch a echoue." }

    Write-Step "Verification Python et calcul reel sur le GPU"
    $Probe = @'
import sys
import torch

print(f"Python          : {sys.version.split()[0]}")
print(f"PyTorch         : {torch.__version__}")
print(f"Runtime CUDA    : {torch.version.cuda}")
print(f"CUDA disponible : {torch.cuda.is_available()}")
if not torch.cuda.is_available():
    raise SystemExit("PyTorch est installe mais CUDA n'est pas disponible")

device = torch.device("cuda:0")
props = torch.cuda.get_device_properties(device)
print(f"GPU             : {props.name}")
print(f"VRAM            : {props.total_memory / 1024**3:.2f} GiB")

a = torch.arange(1, 1_000_001, dtype=torch.float32, device=device)
result = (a * a).sum()
torch.cuda.synchronize()
print(f"Calcul test     : {result.item():.6e}")
print("GPU_TEST_OK")
'@
    $Probe | & $Python -
    if ($LASTEXITCODE -ne 0) { throw "Le test CUDA reel a echoue." }

    Write-Step "Resume"
    Write-Host "PyTorch CUDA est installe et la RTX a execute un calcul." -ForegroundColor Green
}
catch {
    $ExitCode = 1
    Write-Host "`nECHEC: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Si l'installation a reussi mais pas CUDA, une mise a jour du pilote NVIDIA peut etre necessaire." -ForegroundColor Yellow
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
