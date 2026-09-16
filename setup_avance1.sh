#!/usr/bin/env bash
# =============================================================================
# setup_avance1.sh
# Automatiza: labels + milestone + 10 issues de la Parte 1 (Avance 1 - Semana 6)
# Requiere: GitHub CLI instalado y autenticado (gh auth login)
# Uso: ejecutar DENTRO del repo local (git clone ya hecho, remote configurado)
#      chmod +x setup_avance1.sh
#      ./setup_avance1.sh
# =============================================================================

set -e  # detener el script si algo falla

echo "== Verificando autenticación de gh =="
gh auth status || { echo "Corre 'gh auth login' primero"; exit 1; }

# -----------------------------------------------------------------------------
# 1. LABELS
# -----------------------------------------------------------------------------
echo "== Creando labels =="

declare -A LABELS=(
  ["storage"]="1f77b4"
  ["indexes"]="ff7f0e"
  ["query-engine"]="2ca02c"
  ["concurrency"]="d62728"
  ["frontend"]="9467bd"
  ["benchmarks"]="8c564b"
  ["parte-1"]="c5def5"
  ["parte-2"]="c5def5"
  ["parte-3"]="c5def5"
  ["parte-4"]="c5def5"
  ["parte-5"]="c5def5"
)

for label in "${!LABELS[@]}"; do
  color="${LABELS[$label]}"
  gh label create "$label" --color "$color" --force
done

# -----------------------------------------------------------------------------
# 2. MILESTONE (solo el de este avance; los demás los puedes correr después)
# -----------------------------------------------------------------------------
echo "== Creando milestone Avance 1 =="

# gh no tiene comando nativo para milestones -> usamos la API REST
gh api repos/:owner/:repo/milestones -f title="Avance 1 - Semana 6" \
  -f state="open" \
  -f description="Parte 1 completa: relacional (storage, índices, parser, concurrencia, frontend, benchmarks)" \
  || echo "El milestone ya existe, continuando..."

# -----------------------------------------------------------------------------
# 3. ISSUES DE LA PARTE 1
# -----------------------------------------------------------------------------
echo "== Creando issues de la Parte 1 =="

create_issue () {
  local title="$1"
  local labels="$2"
  local body="$3"
  gh issue create \
    --title "$title" \
    --label "$labels" \
    --milestone "Avance 1 - Semana 6" \
    --body "$body"
}

create_issue "Heap File" "storage,parte-1" "$(cat <<'EOF'
- [ ] Diseñar formato de página (header, slots, espacio libre)
- [ ] Implementar escritura/lectura de registros en páginas de disco
- [ ] Implementar inserción en orden de llegada
- [ ] Implementar eliminación lógica (marcar como borrado)
- [ ] Implementar estrategia de reutilización de espacios libres
- [ ] Implementar búsqueda secuencial por clave
- [ ] Tests unitarios (insertar, buscar, eliminar, reutilizar espacio)
EOF
)"

create_issue "Archivo Secuencial Paginado" "storage,parte-1" "$(cat <<'EOF'
- [ ] Diseñar estructura de páginas ordenadas + área auxiliar
- [ ] Implementar inserción manteniendo el orden por clave
- [ ] Implementar eliminación lazy
- [ ] Implementar condición de disparo de reorganización (>30% espacio desperdiciado)
- [ ] Implementar proceso de reorganización
- [ ] Implementar búsqueda binaria sobre páginas ordenadas
- [ ] Tests unitarios (orden se mantiene, reorganización se dispara)
EOF
)"

create_issue "Índice B+ Tree Agrupado" "indexes,parte-1" "$(cat <<'EOF'
- [ ] Definir estructura de nodo (interno/hoja) y factor de bifurcación
- [ ] Implementar inserción con split de nodos
- [ ] Implementar eliminación con merge/redistribución
- [ ] Implementar búsqueda por igualdad
- [ ] Implementar búsqueda por rango (hojas enlazadas)
- [ ] Persistir el árbol en disco
- [ ] Tests unitarios + prueba de estrés
EOF
)"

create_issue "Índice B+ Tree No Agrupado" "indexes,parte-1" "$(cat <<'EOF'
- [ ] Adaptar el B+ agrupado para almacenar punteros (RID)
- [ ] Implementar resolución de puntero -> registro real
- [ ] Tests comparando resultados vs índice agrupado
EOF
)"

create_issue "Índice Hash Dinámico (Extendible Hashing)" "indexes,parte-1" "$(cat <<'EOF'
- [ ] Implementar directorio global y buckets
- [ ] Implementar función hash y profundidad local/global
- [ ] Implementar inserción con split de bucket y duplicación de directorio
- [ ] Implementar búsqueda por igualdad
- [ ] Implementar eliminación (merge de buckets, opcional)
- [ ] Tests unitarios + prueba de colisiones
EOF
)"

create_issue "Algoritmos Externos (Sort, Group By, Join)" "query-engine,parte-1" "$(cat <<'EOF'
- [ ] Implementar External Sorting (k-way merge) para ORDER BY
- [ ] Implementar External Hashing para GROUP BY
- [ ] Implementar JOIN optimizado (índices o external hash join)
- [ ] Definir cuándo el optimizador elige índice vs algoritmo externo
- [ ] Tests con datasets simulando buffer limitado
EOF
)"

create_issue "Parser SQL" "query-engine,parte-1" "$(cat <<'EOF'
- [ ] Definir gramática mínima (SELECT, WHERE, ORDER BY, GROUP BY, INSERT, DELETE)
- [ ] Implementar tokenizer/lexer
- [ ] Implementar parser (a mano o con lark/ply)
- [ ] Construir plan lógico de ejecución desde el AST
- [ ] Conectar el plan con storage/índices
- [ ] Manejo de errores de sintaxis
- [ ] Tests con las 4 sentencias de ejemplo del enunciado
EOF
)"

create_issue "Transacciones y Concurrencia" "concurrency,parte-1" "$(cat <<'EOF'
- [ ] Implementar BEGIN TRANSACTION / END TRANSACTION
- [ ] Implementar mecanismo de locks (shared/exclusive)
- [ ] Prevenir/gestionar deadlocks (timeout o wait-die)
- [ ] Simulación con threading: N transacciones concurrentes
- [ ] Forzar escenario de race condition sin control de concurrencia
- [ ] Mostrar escenario resuelto correctamente con locks
- [ ] Documentar/loggear orden de ejecución para el demo
EOF
)"

create_issue "Interfaz Gráfica (Frontend)" "frontend,parte-1" "$(cat <<'EOF'
- [ ] Elegir stack (PyQt/PySide, Tkinter, o web + API REST)
- [ ] Panel de Archivos: tablas cargadas y su esquema
- [ ] Panel de Consultas: editor SQL
- [ ] Panel de Resultados: tabla con resultados
- [ ] Panel de Plan de Ejecución: índice/algoritmo usado y orden de operaciones
- [ ] Conectar los 4 paneles al motor end-to-end
EOF
)"

create_issue "Comparación Experimental Parte 1" "benchmarks,parte-1" "$(cat <<'EOF'
- [ ] Script de generación de datasets (1K, 10K, 100K registros)
- [ ] Medir Heap File vs Archivo Secuencial (inserción, búsqueda PK, espacio, reorganización)
- [ ] Medir B+ agrupado vs B+ no agrupado vs Hash Dinámico (igualdad, rango, construcción, espacio)
- [ ] Generar gráficas comparativas (matplotlib/plotly)
- [ ] Redactar tabla resumen con ventajas/desventajas
- [ ] Redactar conclusiones
EOF
)"

echo "== Listo. Revisa 'gh issue list --milestone \"Avance 1 - Semana 6\"' =="
echo "== Nota: las issues NO se agregan solas al Project (tablero). =="
echo "== Activa 'Auto-add to project' en Project > ... > Workflows, =="
echo "== o agrégalas manualmente / con 'gh project item-add'. =="
