param(
    [int]$WaitForDownloadPid = 0,
    [switch]$SkipPreparation
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
$runName = 'multimedia_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
$logs = Join-Path $repo "benchmarks\results\smoke\${runName}_logs"
$output = Join-Path $repo "benchmarks\results\smoke\$runName"
New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Write-RunLog([string]$message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    Add-Content -LiteralPath (Join-Path $logs 'status.log') -Value $line
}

function Run-Stage([string]$name, [string[]]$arguments) {
    Write-RunLog "Iniciando $name"
    $out = Join-Path $logs "$name.stdout.log"
    $err = Join-Path $logs "$name.stderr.log"
    $process = Start-Process -FilePath $python -ArgumentList $arguments `
        -WorkingDirectory $repo -RedirectStandardOutput $out `
        -RedirectStandardError $err -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "$name falló con código $($process.ExitCode). Revisa $err"
    }
    Write-RunLog "Terminado $name"
}

try {
    if (-not (Test-Path -LiteralPath $python)) { throw "Falta el Python de .venv: $python" }
    $env:PYTHONUNBUFFERED = '1'
    Write-RunLog "Repositorio: $repo"
    Write-RunLog "Resultado esperado: $output"
    if ($WaitForDownloadPid -gt 0) {
        $download = Get-Process -Id $WaitForDownloadPid -ErrorAction SilentlyContinue
        if ($download) {
            Write-RunLog "Esperando descarga actual (PID $WaitForDownloadPid)"
            Wait-Process -Id $WaitForDownloadPid
        }
    }
    $images = Join-Path $repo 'datasets\coco2017\train2017'
    $annotations = Join-Path $repo 'datasets\coco2017\annotations\instances_train2017.json'
    if (-not (Test-Path -LiteralPath $images -PathType Container) -or
        -not (Test-Path -LiteralPath $annotations -PathType Leaf)) {
        throw 'La descarga no está completa; faltan imágenes o anotaciones. No se ejecutarán las siguientes etapas.'
    }

    if (-not $SkipPreparation) {
        Run-Stage 'create_subsets' @('scripts\create_subsets.py')
    }
    foreach ($size in @(1, 10, 100)) {
        $manifest = Join-Path $repo "datasets\coco_subsets\coco${size}k\instances_subset.json"
        if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Falta $manifest" }
    }
    if (-not $SkipPreparation) {
        Run-Stage 'generate_queries' @('scripts\generate_queries.py')
    }
    foreach ($size in @(1, 10, 100)) {
        $queries = Join-Path $repo "datasets\coco_subsets\coco${size}k\queries.json"
        if (-not (Test-Path -LiteralPath $queries -PathType Leaf)) { throw "Falta $queries" }
    }
    Run-Stage 'multimedia_compare' @('-m', 'benchmarks.multimedia_compare', '--output', $output)
    if (-not (Test-Path -LiteralPath (Join-Path $output 'report.md') -PathType Leaf)) {
        throw 'El benchmark terminó sin report.md'
    }
    Write-RunLog "COMPLETADO: $output"
} catch {
    Write-RunLog "ERROR: $($_.Exception.Message)"
    exit 1
}
