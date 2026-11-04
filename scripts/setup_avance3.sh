#!/usr/bin/env bash
# Setup Avance 3: descarga del dataset MS-COCO 2017
# Ejecutar desde la raiz del proyecto:
#   bash scripts/setup_avance3.sh

set -e

echo "Setup Avance 3: Descargando MS-COCO 2017"

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 no esta instalado." >&2
    exit 1
fi

python3 scripts/download_coco.py

echo "Setup completado."