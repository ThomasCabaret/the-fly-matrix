$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Uv = Join-Path $Root "tools\uv\uv.exe"
$InstallRoot = Join-Path $Root "runs\reference-env\uv-python"
$CacheRoot = Join-Path $Root "runs\reference-env\uv-cache"
$Environment = Join-Path $Root "runs\reference-env\brian2-2.5.1"

Write-Host "[1/4] Checking uv..."
if (-not (Test-Path -LiteralPath $Uv)) {
    throw "tools\uv\uv.exe is missing. Run setup.bat or place the official uv executable there."
}
& $Uv --version

Write-Host "[2/4] Installing isolated Python 3.10..."
$env:UV_PYTHON_INSTALL_DIR = $InstallRoot
$env:UV_CACHE_DIR = $CacheRoot
& $Uv python install 3.10
if ($LASTEXITCODE -ne 0) { throw "uv python install failed" }

Write-Host "[3/4] Creating isolated environment..."
& $Uv venv $Environment --python 3.10
if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }

Write-Host "[4/4] Installing the pinned historical stack..."
$Python = Join-Path $Environment "Scripts\python.exe"
& $Uv pip install --python $Python `
    "brian2==2.5.1" "numpy==1.22.3" "scipy==1.8.1" "sympy==1.12" `
    "cython==0.29.33" "setuptools==67.8.0"
if ($LASTEXITCODE -ne 0) { throw "Pinned package installation failed" }

& $Python -c "import brian2,numpy,scipy,sys; print('[READY] Python',sys.version.split()[0],'Brian2',brian2.__version__,'NumPy',numpy.__version__,'SciPy',scipy.__version__)"
