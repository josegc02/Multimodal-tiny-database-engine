# =============================================================================
# setup_avance1.ps1
# Automatiza: labels + milestone + 10 issues de la Parte 1 (Avance 1 - Semana 6)
# =============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ghPath = "gh"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    if (Test-Path "C:\Program Files\GitHub CLI\gh.exe") {
        $ghPath = "C:\Program Files\GitHub CLI\gh.exe"
    } else {
        Write-Error "GitHub CLI (gh) no está instalado o no se encuentra en el PATH."
        exit 1
    }
}

Write-Host "== Verificando autenticación de gh ==" -ForegroundColor Cyan
& $ghPath auth status
if ($LASTEXITCODE -ne 0) {
    Write-Host "Por favor ejecuta 'gh auth login' primero para autenticarte." -ForegroundColor Red
    exit 1
}

Write-Host "== Creando labels ==" -ForegroundColor Cyan
$labels = [ordered]@{
    "storage"      = "1f77b4"
    "indexes"      = "ff7f0e"
    "query-engine" = "2ca02c"
    "concurrency"  = "d62728"
    "frontend"     = "9467bd"
    "benchmarks"   = "8c564b"
    "parte-1"      = "c5def5"
    "parte-2"      = "c5def5"
    "parte-3"      = "c5def5"
    "parte-4"      = "c5def5"
    "parte-5"      = "c5def5"
}

foreach ($item in $labels.GetEnumerator()) {
    Write-Host "Creando label: $($item.Key)"
    & $ghPath label create $item.Key --color $item.Value --force
}

Write-Host "== Creando milestone Avance 1 ==" -ForegroundColor Cyan
try {
    & $ghPath api repos/:owner/:repo/milestones -f title="Avance 1 - Semana 6" -f state="open" -f description="Parte 1 completa: relacional (storage, índices, parser, concurrencia, frontend, benchmarks)"
} catch {
    Write-Host "El milestone ya existe o continuó con error menor..."
}

Write-Host "== Creando issues de la Parte 1 ==" -ForegroundColor Cyan

function Create-Issue($title, $issueLabels, $body) {
    Write-Host "Creando issue: $title"
    & $ghPath issue create --title $title --label $issueLabels --milestone "Avance 1 - Semana 6" --body $body
}

Create-Issue "Heap File" "storage,parte-1" @"
- [ ] Diseñar formato de página (header, slots, espacio libre)
- [ ] Implementar escritura/lectura de registros en páginas de disco
- [ ] Implementar inserción en orden de llegada
- [ ] Implementar eliminación lógica (marcar como borrado)
- [ ] Implementar estrategia de reutilización de espacios libres
- [ ] Implementar búsqueda secuencial por clave
- [ ] Tests unitarios (insertar, buscar, eliminar, reutilizar espacio)
"@

Create-Issue "Archivo Secuencial Paginado" "storage,parte-1" @"
- [ ] Diseñar estructura de páginas ordenadas + área auxiliar
- [ ] Implementar inserción manteniendo el orden por clave
- [ ] Implementar eliminación lazy
- [ ] Implementar condición de disparo de reorganización (>30% espacio desperdiciado)
- [ ] Implementar proceso de reorganización
- [ ] Implementar búsqueda binaria sobre páginas ordenadas
- [ ] Tests unitarios (orden se mantiene, reorganización se dispara)
"@

Create-Issue "Índice B+ Tree Agrupado" "indexes,parte-1" @"
- [ ] Definir estructura de nodo (interno/hoja) y factor de bifurcación
- [ ] Implementar inserción con split de nodos
- [ ] Implementar eliminación con merge/redistribución
- [ ] Implementar búsqueda por igualdad
- [ ] Implementar búsqueda por rango (hojas enlazadas)
- [ ] Persistir el árbol en disco
- [ ] Tests unitarios + prueba de estrés
"@

Create-Issue "Índice B+ Tree No Agrupado" "indexes,parte-1" @"
- [ ] Adaptar el B+ agrupado para almacenar punteros (RID)
- [ ] Implementar resolución de puntero -> registro real
- [ ] Tests comparando resultados vs índice agrupado
"@

Create-Issue "Índice Hash Dinámico (Extendible Hashing)" "indexes,parte-1" @"
- [ ] Implementar directorio global y buckets
- [ ] Implementar función hash y profundidad local/global
- [ ] Implementar inserción con split de bucket y duplicación de directorio
- [ ] Implementar búsqueda por igualdad
- [ ] Implementar eliminación (merge de buckets, opcional)
- [ ] Tests unitarios + prueba de colisiones
"@

Create-Issue "Algoritmos Externos (Sort, Group By, Join)" "query-engine,parte-1" @"
- [ ] Implementar External Sorting (k-way merge) para ORDER BY
- [ ] Implementar External Hashing para GROUP BY
- [ ] Implementar JOIN optimizado (índices o external hash join)
- [ ] Definir cuándo el optimizador elige índice vs algoritmo externo
- [ ] Tests con datasets simulando buffer limitado
"@

Create-Issue "Parser SQL" "query-engine,parte-1" @"
- [ ] Definir gramática mínima (SELECT, WHERE, ORDER BY, GROUP BY, INSERT, DELETE)
- [ ] Implementar tokenizer/lexer
- [ ] Implementar parser (a mano o con lark/ply)
- [ ] Construir plan lógico de ejecución desde el AST
- [ ] Conectar el plan con storage/índices
- [ ] Manejo de errores de sintaxis
- [ ] Tests con las 4 sentencias de ejemplo del enunciado
"@

Create-Issue "Transacciones y Concurrencia" "concurrency,parte-1" @"
- [ ] Implementar BEGIN TRANSACTION / END TRANSACTION
- [ ] Implementar mecanismo de locks (shared/exclusive)
- [ ] Prevenir/gestionar deadlocks (timeout o wait-die)
- [ ] Simulación con threading: N transacciones concurrentes
- [ ] Forzar escenario de race condition sin control de concurrencia
- [ ] Mostrar escenario resuelto correctamente con locks
- [ ] Documentar/loggear orden de ejecución para el demo
"@

Create-Issue "Interfaz Gráfica (Frontend)" "frontend,parte-1" @"
- [ ] Elegir stack (PyQt/PySide, Tkinter, o web + API REST)
- [ ] Panel de Archivos: tablas cargadas y su esquema
- [ ] Panel de Consultas: editor SQL
- [ ] Panel de Resultados: tabla con resultados
- [ ] Panel de Plan de Ejecución: índice/algoritmo usado y orden de operaciones
- [ ] Conectar los 4 paneles al motor end-to-end
"@

Create-Issue "Comparación Experimental Parte 1" "benchmarks,parte-1" @"
- [ ] Script de generación de datasets (1K, 10K, 100K registros)
- [ ] Medir Heap File vs Archivo Secuencial (inserción, búsqueda PK, espacio, reorganización)
- [ ] Medir B+ agrupado vs B+ no agrupado vs Hash Dinámico (igualdad, rango, construcción, espacio)
- [ ] Generar gráficas comparativas (matplotlib/plotly)
- [ ] Redactar tabla resumen con ventajas/desventajas
- [ ] Redactar conclusiones
"@

Write-Host "== Listo. Revisa 'gh issue list --milestone ""Avance 1 - Semana 6""' ==" -ForegroundColor Green
