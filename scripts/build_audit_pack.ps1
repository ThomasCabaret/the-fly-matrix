param(
    [switch]$NoPause,
    [string]$OutputDirectory,
    [int64]$MaxTextFileBytes = 262144,
    [int64]$CodeSampleBudgetBytes = 184320,
    [int64]$MaxIncludedBytes = 1048576,
    [int64]$MaxIncludedLines = 18000
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot "audit-packs"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot $OutputDirectory
}

$AllowedExtensions = @(
    ".bat", ".css", ".html", ".json", ".md", ".ps1", ".py",
    ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"
)

# These trees contain the project's scientific policy, decisions, canonical
# registries and reproducible campaign descriptions. New text files added below
# them are included automatically.
$ExhaustivePrefixes = @(
    ".agents/skills/",
    "benchmarks/profiles/",
    "decisions/",
    "docs/",
    "protocols/"
)

# These calibration trees are compact contracts rather than run output. They are
# included by class so future targets, models and parameter families appear
# without editing this script. Detailed evidence/evaluation/runner records remain
# sampled below to keep the pack useful in an LLM context window.
$CalibrationContractPrefixes = @(
    "calibration/_templates/",
    "calibration/compilers/",
    "calibration/diagnostics/",
    "calibration/evaluation_candidates/",
    "calibration/models/",
    "calibration/parameter_families/",
    "calibration/parameter_sets/",
    "calibration/scopes/",
    "calibration/targets/"
)

# Box and parameter-family records are compact and central to the architecture,
# so their complete classes remain visible. The larger group/wire/validation
# ledger is represented by the current end-to-end path and its templates below.
$LedgerContractPrefixes = @(
    "ledger/boxes/",
    "ledger/parameter_families/"
)

$RootDocuments = @(
    ".env.example",
    "AGENTS.md",
    "PROJECT_STATE.md",
    "README.md",
    "data/derived/README.md",
    "data/raw/README.md",
    "drosophila_virtual_fly_project_contract.md",
    "pyproject.toml",
    "requirements-gpu-cu126.txt",
    "requirements-lock.txt",
    "runs/README.md"
)

# Stable high-level calibration state plus representative current and historical
# lineage records. Campaign/result payloads are deliberately sampled: the pack
# explains the active chain and its scientific gates without copying every fold
# or every old diagnostic trace.
$RepresentativeAuditFiles = @(
    "calibration/README.md",
    "calibration/dependency-dag.yaml",
    "calibration/model-risks.yaml",
    "calibration/state.yaml",
    "calibration/campaigns/actuator-causal-attribution-v1.yaml",
    "calibration/campaigns/feco-calcium-held-out-fit-v0.yaml",
    "calibration/campaigns/front-leg-local-conversion-contract-v0.yaml",
    "calibration/campaigns/motor-actuator-bridge-envelope-v0.yaml",
    "calibration/campaigns/motor-spike-force-pilot-fit-v0.yaml",
    "calibration/campaigns/motor-twitch-temporal-diagnostic-v0.yaml",
    "calibration/campaigns/neural-model-class-brian2-conformance-v1.yaml",
    "calibration/campaigns/neural-model-class-temporal-probes-v1.yaml",
    "calibration/campaigns/population-dynamics-front-leg-accounting-v0.yaml",
    "calibration/evidence/front-leg-local-conversion-sources-v0.yaml",
    "calibration/evidence/front-leg-local-source-subsets-v0.yaml",
    "calibration/evidence/front-leg-motor-class-ensemble-v0.yaml",
    "calibration/evidence/front-leg-population-dynamics-v0.yaml",
    "calibration/evidence/motor-spike-force-parser-v0.yaml",
    "calibration/evaluations/feco-calcium-held-out-fit-v0.yaml",
    "calibration/evaluations/front-leg-local-conversion-contract-v0.yaml",
    "calibration/evaluations/motor-actuator-bridge-envelope-v0.yaml",
    "calibration/evaluations/motor-spike-force-pilot-fit-v0.yaml",
    "calibration/evaluations/motor-twitch-temporal-diagnostic-v0.yaml",
    "calibration/evaluations/neural-model-class-gate-v0.yaml",
    "calibration/evaluations/population-dynamics-front-leg-accounting-v0.yaml",
    "calibration/runner/actuator-causal-attribution-v1.yaml",
    "calibration/runner/front-leg-local-conversion-contract-v0.yaml",
    "calibration/runner/front-leg-local-source-data-v0.yaml",
    "calibration/runner/motor-actuator-bridge-envelope-v0.yaml",
    "calibration/runner/neural-model-class-brian2-conformance-v1.yaml",
    "calibration/runner/neural-model-class-temporal-probes-v1.yaml",
    "calibration/runner/population-dynamics-front-leg-accounting-v0.yaml",
    "wiring/revalidation/rules-v1.yaml",
    "ledger/README.md",
    "ledger/behaviors.yaml",
    "ledger/datasets.yaml",
    "ledger/groups/_template.yaml",
    "ledger/groups/motor-vnc.yaml",
    "ledger/groups/sensory-proprioceptive.yaml",
    "ledger/groups/sensory-tactile.yaml",
    "ledger/groups/sensory-visual.yaml",
    "ledger/wires/_template.yaml",
    "ledger/wires/body-to-proprioception.yaml",
    "ledger/wires/body-to-world.yaml",
    "ledger/wires/cns-to-motor-routing.yaml",
    "ledger/wires/motor-routing-to-transduction.yaml",
    "ledger/wires/motor-transduction-to-body.yaml",
    "ledger/wires/proprioception-routing-to-cns.yaml",
    "ledger/wires/proprioception-sensor-to-transduction.yaml",
    "ledger/wires/proprioception-transduction-to-routing.yaml",
    "ledger/wires/touch-routing-to-cns.yaml",
    "ledger/wires/touch-sensor-to-transduction.yaml",
    "ledger/wires/touch-transduction-to-routing.yaml",
    "ledger/wires/vision-routing-to-cns.yaml",
    "ledger/wires/vision-sensor-to-transduction.yaml",
    "ledger/wires/vision-transduction-to-routing.yaml",
    "ledger/wires/world-to-touch.yaml",
    "ledger/wires/world-to-vision.yaml",
    "ledger/validations/_template.yaml",
    "ledger/validations/central-graph-runtime.yaml",
    "ledger/validations/closed-loop.yaml",
    "ledger/validations/ledger-integrity.yaml",
    "ledger/validations/peripheral-parameter-compiler.yaml",
    "ledger/validations/scientific-wiring-reaudit.yaml",
    "ledger/validations/signed-dynamics-contract.yaml"
)

$PriorityLaunchers = @(
    "build_audit_pack.bat",
    "calibration_status.bat",
    "download_data.bat",
    "fit_feco_calcium_observation.bat",
    "local_conversion_contract.bat",
    "motor_actuator_bridge_envelope.bat",
    "population_dynamics_assignment.bat",
    "prepare_local_source_data.bat",
    "run_analysis.bat",
    "setup.bat",
    "wiring_revalidation.bat"
)

# Whole files, not rewritten excerpts. The budget prevents implementation code
# from crowding out policy. Update this short list only when a new subsystem is
# important enough that an external reviewer needs to inspect its implementation.
$PriorityCodeSamples = @(
    "src/the_fly_matrix/central_graph.py",
    "src/the_fly_matrix/calibration_registry.py",
    "src/the_fly_matrix/calibration_runner.py",
    "src/the_fly_matrix/feco_calcium_fit.py",
    "src/the_fly_matrix/motor_actuator_bridge.py",
    "tests/test_motor_actuator_bridge.py",
    "scripts/build_audit_pack.ps1"
)

$RequiredAuditPaths = @(
    "AGENTS.md",
    "PROJECT_STATE.md",
    "README.md",
    "docs/calibration-methodology.md",
    "docs/reproduction-pipeline.md",
    "docs/wiring-methodology.md",
    "calibration/README.md",
    "calibration/dependency-dag.yaml",
    "calibration/model-risks.yaml",
    "calibration/state.yaml",
    "calibration/targets/population-dynamics-assignment-v0.yaml",
    "calibration/campaigns/motor-actuator-bridge-envelope-v0.yaml",
    "calibration/evaluations/motor-actuator-bridge-envelope-v0.yaml",
    "decisions/0016-event-capable-typed-hybrid-neural-runtime.md",
    "ledger/README.md",
    "scripts/build_audit_pack.ps1"
)

$AlwaysExcludedPrefixes = @(
    ".git/", ".venv/", ".cache/", "audit-packs/", "data/raw/",
    "data/derived/", "reports/generated/", "runs/", "tools/uv/",
    "ui/wiring-map/node_modules/", "ui/wiring-map/dist/"
)

$ExitCode = 0
$StageRoot = $null

function Normalize-RelativePath([string]$Path) {
    # git ls-files already returns repository-relative paths. In particular, do
    # not trim leading dots: .agents and .env.example are meaningful names.
    return $Path.Replace("\", "/")
}

function Starts-WithAny([string]$Path, [string[]]$Prefixes) {
    foreach ($Prefix in $Prefixes) {
        if ($Path.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-LineCount([string]$Path) {
    $Count = 0
    $Reader = [System.IO.File]::OpenText($Path)
    try {
        while ($null -ne $Reader.ReadLine()) { $Count++ }
    } finally {
        $Reader.Dispose()
    }
    return $Count
}

function Copy-AuditFile([string]$RelativePath, [string]$Category) {
    $Source = Join-Path $ProjectRoot ($RelativePath.Replace("/", "\"))
    $Destination = Join-Path $PackRoot ($RelativePath.Replace("/", "\"))
    $DestinationParent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $DestinationParent)) {
        [void](New-Item -ItemType Directory -Path $DestinationParent -Force)
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    $Item = Get-Item -LiteralPath $Source
    $Lines = Get-LineCount $Source
    $Hash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:Included.Add([pscustomobject]@{
        path = $RelativePath
        category = $Category
        bytes = $Item.Length
        lines = $Lines
        sha256 = $Hash
    })
}

try {
    Write-Host "The Fly Matrix - pack d'audit externe" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    Write-Host "Sortie : $OutputDirectory"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git est requis pour inventorier les fichiers suivis et non suivis non ignores."
    }

    Push-Location $ProjectRoot
    try {
        $Tracked = @(& git ls-files)
        if ($LASTEXITCODE -ne 0) { throw "git ls-files a echoue." }
        $Untracked = @(& git ls-files --others --exclude-standard)
        if ($LASTEXITCODE -ne 0) { throw "git ls-files --others a echoue." }
        $Commit = (& git rev-parse HEAD).Trim()
        $Branch = (& git branch --show-current).Trim()
        $DirtyLines = @(& git status --porcelain)
    } finally {
        Pop-Location
    }

    $SourceKinds = @{}
    foreach ($Path in $Tracked) {
        if (-not [string]::IsNullOrWhiteSpace($Path)) {
            $SourceKinds[(Normalize-RelativePath $Path)] = "tracked"
        }
    }
    foreach ($Path in $Untracked) {
        if (-not [string]::IsNullOrWhiteSpace($Path)) {
            $Normalized = Normalize-RelativePath $Path
            if (-not $SourceKinds.ContainsKey($Normalized)) {
                $SourceKinds[$Normalized] = "untracked"
            }
        }
    }

    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $ArchiveName = "the-fly-matrix-audit-$Stamp.zip"
    [void](New-Item -ItemType Directory -Path $OutputDirectory -Force)
    $ArchivePath = Join-Path $OutputDirectory $ArchiveName
    $StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("flymatrix-audit-" + [guid]::NewGuid().ToString("N"))
    $PackRoot = Join-Path $StageRoot "the-fly-matrix-audit"
    [void](New-Item -ItemType Directory -Path $PackRoot -Force)

    $Included = [System.Collections.Generic.List[object]]::new()
    $Omitted = [System.Collections.Generic.List[object]]::new()
    $Selected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $CodeBytes = 0L

    Write-Host "`n[1/4] Selection des sources textuelles" -ForegroundColor Cyan
    $Candidates = @($SourceKinds.Keys | Sort-Object)
    foreach ($RelativePath in $Candidates) {
        $FullPath = Join-Path $ProjectRoot ($RelativePath.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) { continue }

        $Extension = [System.IO.Path]::GetExtension($RelativePath).ToLowerInvariant()
        $IsAllowedText = ($AllowedExtensions -contains $Extension) -or ($RelativePath -eq ".env.example")
        $Reason = $null
        $Category = $null

        if ($RootDocuments -contains $RelativePath) {
            $Category = "root-policy-and-environment"
        } elseif (Starts-WithAny $RelativePath $AlwaysExcludedPrefixes) {
            $Reason = "excluded-resource-or-generated-tree"
        } elseif (-not $IsAllowedText) {
            $Reason = "non-text-or-unsupported-extension"
        } elseif ($RelativePath -match '(^|/)(\.env|[^/]*(secret|token|credential|private-key)[^/]*)$' -and $RelativePath -ne ".env.example") {
            $Reason = "secret-risk-name"
        } elseif ($PriorityLaunchers -contains $RelativePath) {
            $Category = "launcher"
        } elseif ((Starts-WithAny $RelativePath $ExhaustivePrefixes) -or
                  (Starts-WithAny $RelativePath $CalibrationContractPrefixes) -or
                  (Starts-WithAny $RelativePath $LedgerContractPrefixes)) {
            $Category = "policy-status-and-reproducibility"
        } elseif ($RepresentativeAuditFiles -contains $RelativePath) {
            $Category = "representative-scientific-lineage"
        } elseif ($PriorityCodeSamples -contains $RelativePath) {
            $Category = "implementation-sample"
        } else {
            $Reason = "outside-audit-scope"
        }

        $Item = Get-Item -LiteralPath $FullPath
        if ($null -eq $Reason -and $Item.Length -gt $MaxTextFileBytes) {
            $Reason = "file-size-limit"
            $Category = $null
        }
        if ($null -eq $Reason -and $Category -eq "implementation-sample") {
            if (($CodeBytes + $Item.Length) -gt $CodeSampleBudgetBytes) {
                $Reason = "code-sample-budget"
                $Category = $null
            } else {
                $CodeBytes += $Item.Length
            }
        }

        if ($null -ne $Category) {
            Copy-AuditFile $RelativePath $Category
            [void]$Selected.Add($RelativePath)
        } else {
            $Omitted.Add([pscustomobject]@{
                path = $RelativePath
                source_state = $SourceKinds[$RelativePath]
                bytes = $Item.Length
                reason = $Reason
            })
        }
    }

    Write-Host ("      {0} fichiers copies; {1} fichiers inventories mais omis." -f $Included.Count, $Omitted.Count)

    $MissingRequired = @($RequiredAuditPaths | Where-Object { -not $Selected.Contains($_) })
    if ($MissingRequired.Count -gt 0) {
        throw "Pack incomplet; fichiers d'audit requis absents : $($MissingRequired -join ', ')"
    }
    $SourceBytes = [int64](($Included | Measure-Object -Property bytes -Sum).Sum)
    $SourceLines = [int64](($Included | Measure-Object -Property lines -Sum).Sum)
    if ($SourceBytes -gt $MaxIncludedBytes) {
        throw "Pack trop volumineux avant compression : $SourceBytes octets > budget $MaxIncludedBytes. Revoir l'echantillonnage explicitement."
    }
    if ($SourceLines -gt $MaxIncludedLines) {
        throw "Pack trop long : $SourceLines lignes > budget $MaxIncludedLines. Revoir l'echantillonnage explicitement."
    }
    Write-Host ("      Budget : {0}/{1} lignes; {2}/{3} octets." -f $SourceLines, $MaxIncludedLines, $SourceBytes, $MaxIncludedBytes)

    Write-Host "`n[2/4] Ecriture du contexte et des manifestes" -ForegroundColor Cyan
    $Dirty = if ($DirtyLines.Count -gt 0) { "yes" } else { "no" }
    $Readme = @"
# The Fly Matrix — external audit pack

This is a bounded, text-only snapshot intended for review by another human or
language model. It is not a runnable checkout and deliberately excludes raw and
derived datasets, generated reports, run outputs, environments, dependencies,
large resources, secrets and most implementation code.

- Generated: $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssK")
- Git branch: $Branch
- Git commit: $Commit
- Working tree dirty when captured: $Dirty
- Included files: $($Included.Count)
- Omitted inventoried files: $($Omitted.Count)
- Included source bytes before compression: $([int64](($Included | Measure-Object -Property bytes -Sum).Sum))
- Included source lines: $([int64](($Included | Measure-Object -Property lines -Sum).Sum))

Read `AGENTS.md`, `PROJECT_STATE.md`, `README.md`, `docs/`, `decisions/` and the
included canonical YAML records first. `MANIFEST.tsv` records every copied file
and its SHA-256. `OMISSIONS.tsv` records every tracked or visible non-ignored file
that was not copied and why.

Selection is intentionally asymmetric: policy, decisions and documentation are
complete; calibration contracts are included by class while detailed lineages
are sampled around the active front and decisive historical gates; box and
parameter-family ledgers are complete while groups, wires and validations are
representative; implementation samples are complete source files but only
examples. Do not infer that omitted code or records do not exist. The generator
fails instead of silently exceeding $MaxIncludedLines lines or
$MaxIncludedBytes source bytes.

The archive copies current working-tree contents, so tracked modifications and
eligible untracked files are represented even when `dirty` is `yes`.
"@
    [System.IO.File]::WriteAllText((Join-Path $PackRoot "AUDIT_PACK_README.md"), $Readme, [System.Text.UTF8Encoding]::new($false))

    $ManifestPath = Join-Path $PackRoot "MANIFEST.tsv"
    $ManifestLines = [System.Collections.Generic.List[string]]::new()
    $ManifestLines.Add("path`tcategory`tbytes`tlines`tsha256")
    foreach ($Row in ($Included | Sort-Object path)) {
        $ManifestLines.Add("$($Row.path)`t$($Row.category)`t$($Row.bytes)`t$($Row.lines)`t$($Row.sha256)")
    }
    [System.IO.File]::WriteAllLines($ManifestPath, $ManifestLines, [System.Text.UTF8Encoding]::new($false))

    $OmissionsPath = Join-Path $PackRoot "OMISSIONS.tsv"
    $OmissionLines = [System.Collections.Generic.List[string]]::new()
    $OmissionLines.Add("path`tsource_state`tbytes`treason")
    foreach ($Row in ($Omitted | Sort-Object path)) {
        $OmissionLines.Add("$($Row.path)`t$($Row.source_state)`t$($Row.bytes)`t$($Row.reason)")
    }
    [System.IO.File]::WriteAllLines($OmissionsPath, $OmissionLines, [System.Text.UTF8Encoding]::new($false))

    $StatusPath = Join-Path $PackRoot "GIT_STATUS.txt"
    $StatusText = if ($DirtyLines.Count -gt 0) { ($DirtyLines -join [Environment]::NewLine) } else { "clean" }
    [System.IO.File]::WriteAllText($StatusPath, $StatusText + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

    Write-Host "`n[3/4] Compression" -ForegroundColor Cyan
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ArchivePath) {
        [System.IO.File]::Delete($ArchivePath)
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $StageRoot,
        $ArchivePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    Write-Host "`n[4/4] Verification de l'archive" -ForegroundColor Cyan
    $Zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $EntryCount = $Zip.Entries.Count
        $ActualEntries = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($Entry in $Zip.Entries) {
            [void]$ActualEntries.Add($Entry.FullName.Replace("\", "/"))
        }
        $ExpectedEntries = @(
            $Included.path | ForEach-Object { "the-fly-matrix-audit/$_" }
        ) + @(
            "the-fly-matrix-audit/AUDIT_PACK_README.md",
            "the-fly-matrix-audit/GIT_STATUS.txt",
            "the-fly-matrix-audit/MANIFEST.tsv",
            "the-fly-matrix-audit/OMISSIONS.tsv"
        )
        $MissingEntries = @($ExpectedEntries | Where-Object { -not $ActualEntries.Contains($_) })
        if ($MissingEntries.Count -gt 0) {
            throw "Archive incomplete; entrees absentes : $($MissingEntries -join ', ')"
        }
    } finally {
        $Zip.Dispose()
    }

    $ArchiveItem = Get-Item -LiteralPath $ArchivePath
    Write-Host "`n[OK] Pack d'audit construit." -ForegroundColor Green
    Write-Host "     Archive       : $ArchivePath"
    Write-Host "     Taille ZIP    : $([math]::Round($ArchiveItem.Length / 1KB, 1)) KiB"
    Write-Host "     Sources       : $($Included.Count) fichiers, $([math]::Round($SourceBytes / 1KB, 1)) KiB, $SourceLines lignes"
    Write-Host "     Echant. code  : $([math]::Round($CodeBytes / 1KB, 1)) KiB / $([math]::Round($CodeSampleBudgetBytes / 1KB, 1)) KiB"
    Write-Host "     Omissions     : $($Omitted.Count), detaillees dans OMISSIONS.tsv"
}
catch {
    $ExitCode = 1
    Write-Host "`n[ECHEC] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if ($null -ne $StageRoot -and (Test-Path -LiteralPath $StageRoot)) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
