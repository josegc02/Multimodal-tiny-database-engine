# Comparación experimental — issue #10

Scripts de consola independientes del frontend. Ejecutar desde la raíz del repo:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python benchmarks/bench_storage.py
.venv/bin/python benchmarks/bench_indexes.py
```

También admiten `python -m benchmarks.bench_storage` / `benchmarks.bench_indexes`.
Por defecto usan **1.000, 10.000 y 100.000 registros**, **3 repeticiones** por
tamaño, semilla **42**, y escriben en `benchmarks/results/`. Para validar con
menos datos sin pisar la corrida oficial:

```bash
.venv/bin/python benchmarks/bench_storage.py --sizes 200 1000 5000 --repetitions 1 --output-dir benchmarks/results/smoke
.venv/bin/python benchmarks/bench_indexes.py --sizes 200 1000 5000 --repetitions 1 --output-dir benchmarks/results/smoke
```

Salidas por suite (`storage_*` e `indexes_*`):

- `*_comparison.csv`: media y desviación estándar (`<métrica>_std`) de las repeticiones.
- `*_runs.csv`: cada repetición por separado.
- `*_metadata.json`: entorno, configuración, estadísticas estructurales y duración.
- PNG en escala **log-log** con barras de error (± 1 desviación estándar).
  Inserción, construcción de índices y actualizaciones se grafican **por
  operación** (total ÷ cantidad de operaciones): una curva plana es O(1) u
  O(log N) y una pendiente 1 es O(N). Los CSV guardan los totales.

Para redibujar las gráficas desde los `*_comparison.csv` existentes, sin volver
a medir:

```bash
.venv/bin/python benchmarks/bench_storage.py --solo-graficas
.venv/bin/python benchmarks/bench_indexes.py --solo-graficas
```

Para contrastar la complejidad teórica con la medida:

```bash
.venv/bin/python benchmarks/complexity.py
```

Imprime una tabla markdown con la pendiente log-log de cada curva entre tamaños
consecutivos y su veredicto (usa el último tramo, el asintótico). Termina con
código 1 si alguna curva no coincide con la teoría.

Cada consulta verifica sus resultados fuera de la región cronometrada. Los
archivos de datos se crean con `tempfile.mkdtemp()` y se borran al terminar.

## Metodología

- **Dataset**: IDs únicos 0..N-1 en orden aleatorio, nombres ASCII de 20
  caracteres y precios (36 B por registro); todas las técnicas reciben el mismo
  orden y las mismas claves de consulta.
- **Variación del entorno**: en Windows, la misma corrida puede variar ±25–30%
  entre repeticiones (frecuencia del CPU, antivirus, procesos de fondo). Por
  eso se repite 3 veces y se grafica la desviación estándar. El recolector de
  basura queda activo: un experimento alternando encendido/apagado en la misma
  sesión no mostró diferencias mayores que esa variación.

### Storage (`bench_storage.py`)

- **Inserción** de N registros. En el secuencial incluye las reorganizaciones
  automáticas que dispara la propia carga (`reorganizaciones_automaticas`).
- **Búsqueda PK**: 100 claves existentes. El heap usa
  `search_by_key(..., unique=True)`, que se detiene en la primera coincidencia,
  para no penalizarlo con un scan completo innecesario.
- **Espacio** tras la carga (`main + aux` en el secuencial).
- **Reorganización**: se borra el 35% de las claves (no cronometrado), se
  comprueba el umbral del 30% y se mide solo `reorganize()`. Después se repiten
  las búsquedas de las claves sobrevivientes (escaladas a 100 consultas).
- `paginas_aux_tras_carga`: páginas de `aux` al terminar la carga. La búsqueda
  no las recorre: las claves de `aux` se ubican con un índice en memoria.

### Índices (`bench_indexes.py`)

- **Mismo tamaño de página (4096 B) y nodos llenos**: el B+ agrupado usa
  M = 92 (clave + registro de 36 B por entrada de hoja), el no agrupado M = 254
  (clave + RID de 8 B) y el hash buckets de 254 entradas.
- **Todas las consultas devuelven registros completos**: el agrupado los tiene en
  sus hojas; el no agrupado y el hash leen cada RID de un `HeapFile` real.
- **Igualdad**: 100 claves. **Rango**: 20 rangos `[k, k+100]`. El hash no
  soporta rangos (NA).
- **Ordenamiento** (`ORDER BY id` de toda la tabla): agrupado recorre hojas, no
  agrupado recorre hojas y lee cada RID, y el hash, que no aporta orden, usa
  lo que haría el motor: `heap.scan()` + `external_sort`.
- **Espacio**: `espacio_total_bytes` = tabla + índice (el agrupado es un solo
  archivo). `espacio_adicional_bytes` = total − heap con los mismos N registros.
  `memoria_estimada_bytes` solo aplica al hash (`sys.getsizeof` del grafo).
- **Actualizaciones**: 500 claves nuevas, cada inserción seguida de su
  eliminación, en tabla e índice (1000 operaciones).
- **Durabilidad**: el B+ escribe y hace `flush` de cada página modificada; el
  hash trabaja en RAM y persiste un snapshot JSON completo, que es O(N). Ese
  snapshot se mide aparte (`tiempo_snapshot_seg`) y queda fuera de la
  construcción y de las actualizaciones, para no mezclarlo con su costo O(1)
  por operación. Ninguno fuerza `fsync`.

## Valores NA

| Columna | Significado |
| --- | --- |
| `tiempo_rango_seg` | Hash: no soporta rangos; no equivale a tiempo cero. |
| `memoria_estimada_bytes` | B+: no medida (trabaja sobre archivo). |
| `tiempo_snapshot_seg` | B+: no tiene snapshot (persiste página a página). |
| `paginas_aux_tras_carga` | Heap: no tiene área de desborde. |
| `tiempo_reorganizacion_seg`, `*_post_reorg_*`, `reorganizaciones_automaticas` | Heap: no tiene reorganización. |

Las conclusiones se recogen en `docs/informe.md`.
