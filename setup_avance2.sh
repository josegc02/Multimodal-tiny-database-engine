#!/usr/bin/env bash
# =============================================================================
# setup_avance2.sh
# Automatiza: labels + milestone + 10 issues de la Parte 2 (Entrega Parcial - Semana 8)
# Parte 2: Base de Datos Espacial (R-Tree, consultas espaciales, mapa, benchmarks)
# =============================================================================

set -e

echo "== Verificando autenticación de gh =="
gh auth status || { echo "Corre 'gh auth login' primero"; exit 1; }

echo "== Creando/actualizando labels =="
declare -A LABELS=(
  ["spatial"]="17becf"
  ["indexes"]="ff7f0e"
  ["query-engine"]="2ca02c"
  ["frontend"]="9467bd"
  ["benchmarks"]="8c564b"
  ["datasets"]="bcbd22"
  ["parte-2"]="c5def5"
)

for label in "${!LABELS[@]}"; do
  color="${LABELS[$label]}"
  gh label create "$label" --color "$color" --force
done

milestone="Entrega Parcial - Semana 8"

echo "== Creando milestone '$milestone' =="
gh api repos/:owner/:repo/milestones -f title="$milestone" \
  -f state="open" \
  -f description="Partes 1 y 2 completas: espacial (R-Tree, rango, k-NN, polígonos, SQL espacial, mapa, benchmarks vs GiST)" \
  || echo "El milestone ya existe, continuando..."

echo "== Creando issues de la Parte 2 =="

create_issue () {
  local title="$1"
  local labels="$2"
  local body="$3"
  gh issue create \
    --title "$title" \
    --label "$labels" \
    --milestone "$milestone" \
    --body "$body"
}

create_issue "Índice R-Tree: estructura base" "spatial,indexes,parte-2" "$(cat <<'EOF'
- [ ] Definir estructura de nodo (interno/hoja), MBR y capacidad M / mínimo m
- [ ] Implementar cálculo de MBR, área, enlargement y overlap
- [ ] Implementar inserción (ChooseLeaf + ajuste de MBRs hacia la raíz)
- [ ] Implementar split de nodos (Quadratic o Linear Split)
- [ ] Implementar eliminación (CondenseTree + reinserción)
- [ ] Persistir el árbol en disco (páginas) y cargarlo
- [ ] Tests unitarios (invariantes de MBR, altura balanceada, inserción masiva)
EOF
)"

create_issue "Métricas de distancia: Euclidiana y Haversine" "spatial,parte-2" "$(cat <<'EOF'
- [ ] Implementar distancia Euclidiana (lat/lon como plano)
- [ ] Implementar distancia geodésica Haversine (metros)
- [ ] Implementar MINDIST punto-MBR para ambas métricas (poda en el árbol)
- [ ] Conversión radio en metros -> MBR de búsqueda en grados (filtro grueso)
- [ ] Tests con distancias conocidas (ej. Lima - Cusco)
- [ ] Documentar diferencias/errores entre ambas métricas
EOF
)"

create_issue "Consulta por rango (radio)" "spatial,indexes,parte-2" "$(cat <<'EOF'
- [ ] Implementar búsqueda por rectángulo (MBR intersect)
- [ ] Implementar búsqueda por radio: filtro por MBR + refinamiento con distancia exacta
- [ ] Soportar métrica Euclidiana y Haversine
- [ ] Contar nodos visitados (para el plan de ejecución y benchmarks)
- [ ] Tests comparando contra búsqueda secuencial (mismos resultados)
EOF
)"

create_issue "Consulta k-NN (k vecinos más cercanos)" "spatial,indexes,parte-2" "$(cat <<'EOF'
- [ ] Implementar k-NN best-first con cola de prioridad (MINDIST)
- [ ] Soportar métrica Euclidiana y Haversine
- [ ] Manejar empates y k mayor que el número de puntos
- [ ] Tests comparando contra k-NN por fuerza bruta
EOF
)"

create_issue "Intersección con polígonos" "spatial,parte-2" "$(cat <<'EOF'
- [ ] Representar polígonos (lista de vértices) y calcular su MBR
- [ ] Filtro grueso: puntos del R-Tree que caen en el MBR del polígono
- [ ] Refinamiento: point-in-polygon (ray casting)
- [ ] Cargar polígonos de distritos (GeoJSON, ej. distritos de Lima)
- [ ] Tests con polígonos convexos, cóncavos y puntos en el borde
EOF
)"

create_issue "Extensión SQL espacial" "query-engine,spatial,parte-2" "$(cat <<'EOF'
- [ ] Agregar tipo de columna POINT al esquema de tablas
- [ ] Soportar literal POINT(lat, lon) en el lexer/parser
- [ ] Soportar función distancia(col, POINT(...)) en WHERE (rango)
- [ ] Soportar ORDER BY distancia(...) LIMIT k (k-NN)
- [ ] Soportar intersección con polígono (ej. WITHIN(col, POLYGON(...)) o por distrito)
- [ ] Permitir elegir métrica (ej. USING HAVERSINE / EUCLIDEAN)
- [ ] CREATE INDEX ... USING RTREE y registro en el catálogo
- [ ] Optimizador: usar R-Tree si existe índice, si no búsqueda secuencial
- [ ] Mostrar en el plan de ejecución: índice usado, nodos visitados, filtro/refinamiento
- [ ] Tests con las consultas de ejemplo del enunciado
EOF
)"

create_issue "Panel de Mapa (Frontend)" "frontend,spatial,parte-2" "$(cat <<'EOF'
- [ ] Integrar Leaflet (u otro) con tiles de OpenStreetMap
- [ ] Endpoint/API que devuelva los puntos de una tabla espacial
- [ ] Dibujar todos los puntos de la tabla (clustering si son muchos)
- [ ] Resaltar resultados de la consulta (color distinto)
- [ ] Dibujar círculo del radio / punto de consulta / polígono usado
- [ ] Permitir hacer clic en el mapa para fijar el punto de consulta
- [ ] Conectar con el Panel de Consultas y el Panel de Resultados
EOF
)"

create_issue "Datasets espaciales" "datasets,spatial,parte-2" "$(cat <<'EOF'
- [ ] Elegir dominio (tiendas, restaurantes, gasolineras, etc.)
- [ ] Obtener datos reales (OpenStreetMap / datos abiertos) o generarlos
- [ ] Script de generación de 1K, 10K y 100K puntos dentro de un área (ej. Lima)
- [ ] Obtener polígonos de distritos (GeoJSON)
- [ ] Script de carga a nuestras tablas y a PostgreSQL/PostGIS
EOF
)"

create_issue "Setup PostgreSQL + PostGIS (GiST)" "benchmarks,spatial,parte-2" "$(cat <<'EOF'
- [ ] Levantar PostgreSQL con PostGIS (docker-compose recomendado)
- [ ] Crear tablas con columna geography/geometry
- [ ] Crear índice GiST
- [ ] Escribir las consultas equivalentes (ST_DWithin, ORDER BY <-> LIMIT k, ST_Within)
- [ ] Verificar que los resultados coinciden con nuestro R-Tree
EOF
)"

create_issue "Comparación Experimental Parte 2" "benchmarks,parte-2" "$(cat <<'EOF'
- [ ] Script de benchmark: Secuencial vs R-Tree vs GiST
- [ ] Datasets de 1K, 10K y 100K puntos
- [ ] Consultas por rango: radio 1 km, 5 km, 10 km
- [ ] Consultas k-NN: k = 10, 50, 100
- [ ] Medir tiempo de construcción del índice
- [ ] Medir tiempo de consulta (promedio de 100 consultas aleatorias)
- [ ] Medir uso de memoria y espacio en disco
- [ ] Generar gráficas comparativas (matplotlib/plotly)
- [ ] Tabla resumen: cuándo usar cada técnica
- [ ] Redactar conclusiones en el informe
EOF
)"

echo "== Listo. Revisa 'gh issue list --milestone \"$milestone\"' =="
