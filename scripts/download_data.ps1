param(
    [switch]$NoPause,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Destination = Join-Path $ProjectRoot "data\raw\malecns\v1.0"
$ExitCode = 0

$Files = @(
    @{
        Name = "body-annotations-male-cns-v1.0-minconf-0.5.feather"
        Bytes = 14483314L
        Url = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    },
    @{
        Name = "body-neurotransmitters-male-cns-v1.0.feather"
        Bytes = 43282834L
        Url = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/body-neurotransmitters-male-cns-v1.0.feather"
    },
    @{
        Name = "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
        Bytes = 1051241946L
        Url = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/connectome-weights-male-cns-v1.0-minconf-0.5.feather"
    },
    @{
        Name = "optic-column-type-assignments-v1.0.xlsx"
        Bytes = 111565L
        Url = "https://raw.githubusercontent.com/flyconnectome/2025malecns/main/supplemental_data/optic-column-type-assignments-v1.0.xlsx"
    }
)

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Format-Bytes([long]$Bytes) {
    if ($Bytes -ge 1GB) { return "{0:N2} GiB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MiB" -f ($Bytes / 1MB) }
    return "$Bytes bytes"
}

try {
    Write-Host "The Fly Matrix - MaleCNS v1.0 data bootstrap" -ForegroundColor Green
    Write-Host "Project     : $ProjectRoot"
    Write-Host "Destination : $Destination"
    Write-Host "Files       : $($Files.Count)"

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $Curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    $ChecksumLines = @()
    $Index = 0

    foreach ($Spec in $Files) {
        $Index++
        $Target = Join-Path $Destination $Spec.Name
        $Part = "$Target.part"
        Write-Step "[$Index/$($Files.Count)] $($Spec.Name)"
        Write-Host "Source : $($Spec.Url)"
        Write-Host "Taille : $(Format-Bytes $Spec.Bytes) ($($Spec.Bytes) octets)"

        if ((Test-Path -LiteralPath $Target) -and -not $Force) {
            $Actual = (Get-Item -LiteralPath $Target).Length
            if ($Actual -eq $Spec.Bytes) {
                Write-Host "Etat   : deja present, taille exacte; telechargement ignore." -ForegroundColor Green
            } else {
                $Invalid = "$Target.invalid-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
                Write-Warning "Taille incorrecte: $Actual octets. Conservation sous $Invalid"
                Move-Item -LiteralPath $Target -Destination $Invalid
            }
        }

        if ($Force -and (Test-Path -LiteralPath $Target)) {
            $Backup = "$Target.replaced-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            Write-Warning "-Force demande: l'ancien fichier est conserve sous $Backup"
            Move-Item -LiteralPath $Target -Destination $Backup
        }

        if (-not (Test-Path -LiteralPath $Target)) {
            Write-Host "Etat   : telechargement en cours..." -ForegroundColor Yellow
            if ($Curl) {
                & $Curl.Source --fail --location --retry 3 --retry-delay 2 --continue-at - --output $Part $Spec.Url
                if ($LASTEXITCODE -ne 0) {
                    throw "curl a echoue avec le code $LASTEXITCODE pour $($Spec.Name)"
                }
            } else {
                Write-Host "curl.exe absent: utilisation de Invoke-WebRequest (sans reprise)."
                Invoke-WebRequest -Uri $Spec.Url -OutFile $Part -UseBasicParsing
            }

            $Downloaded = (Get-Item -LiteralPath $Part).Length
            if ($Downloaded -ne $Spec.Bytes) {
                throw "Taille invalide pour $($Spec.Name): $Downloaded, attendu $($Spec.Bytes). Le .part est conserve."
            }
            Move-Item -LiteralPath $Part -Destination $Target
            Write-Host "Etat   : telechargement termine et taille valide." -ForegroundColor Green
        }

        Write-Host "SHA-256: calcul en cours..."
        $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash.ToLowerInvariant()
        $ChecksumLines += "$Hash  $($Spec.Name)"
        Write-Host "SHA-256: $Hash"
    }

    $ChecksumPath = Join-Path $Destination "checksums.sha256"
    $ChecksumLines | Set-Content -LiteralPath $ChecksumPath -Encoding ascii
    Write-Step "Resume"
    Write-Host "Les quatre fichiers MaleCNS sont presents, controles et empreintes." -ForegroundColor Green
    Write-Host "Empreintes : $ChecksumPath"
}
catch {
    $ExitCode = 1
    Write-Host "`nECHEC: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Les fichiers .part ou .invalid sont conserves pour diagnostic/reprise." -ForegroundColor Yellow
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
