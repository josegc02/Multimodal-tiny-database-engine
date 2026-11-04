# Setup Avance 3: descarga del dataset MS-COCO 2017
# Ejecutar desde la raiz del proyecto:
#   .\scripts\setup_avance3.ps1

$ErrorActionPreference = "Stop"

Write-Host "Setup Avance 3: Descargando MS-COCO 2017"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python no esta instalado o no esta en el PATH." -ForegroundColor Red
    exit 1
}

python scripts/download_coco.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error durante la descarga del dataset." -ForegroundColor Red
    exit 1
}

Write-Host "Setup completado."