# Comparación experimental — issue #10

Scripts de consola independientes del frontend. Ejecutar desde la raíz del repo:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python benchmarks/bench_storage.py
.venv/bin/python benchmarks/bench_indexes.py
```

También admiten `python -m benchmarks.bench_storage` / `benchmarks.bench_indexes`.
Por defecto usan **1.000, 10.000 y 100.000 registros**, semilla **42** y escriben
en `benchmarks/results/`. Para validar con menos datos sin pisar la corrida oficial:

```bash
.venv/bin/python benchmarks/bench_storage.py --sizes 100 1000 5000 --output-dir benchmarks/results/smoke
.venv/bin/python benchmarks/bench_indexes.py --sizes 100 1000 5000 --output-dir benchmarks/results/smoke
```

Los CSV contienen tiempos totales en segundos, no promedios por operación.
Cada consulta verifica sus resultados fuera de la región cronometrada. Las
tablas se imprimen al terminar; los mensajes de avance van a stderr. Los archivos
de datos se crean con `tempfile.mkdtemp()` y se limpian al terminar, incluso si
falla una comprobación. No se cambian los motores ni sus algoritmos.

## Metodología

- Dataset: IDs únicos desordenados, nombres ASCII de 20 caracteres y precios;
  todas las técnicas reciben el mismo orden y las mismas claves de consulta.
- Storage: inserción de N registros y 100 búsquedas existentes. El espacio se
  mide antes de borrar. En secuencial se eliminan 35% de claves usando RIDs
  actuales y se comprueba `needs_reorganization()`. Solo `reorganize()` está
  cronometrado; scan, borrado y verificación se excluyen. El overflow puede haber
  activado ya el umbral antes de las eliminaciones.
- Índices: páginas B+ de 4096 B, máximo **64 claves por nodo**; hash con **64
  entradas por bucket**, profundidad máxima 16. Se usan las APIs existentes.
  El agrupado recibe registros completos; los otros reciben RIDs sintéticos,
  sin leer un heap. La búsqueda mide 100 igualdades y 20 rangos inclusivos
  `[k, min(N-1, k+100)]`, de hasta 101 entradas.
- Actualizaciones: 500 claves nuevas mayores que las originales, en orden
  aleatorio; cada inserción va seguida de su eliminación (1000 operaciones).
  No se borran registros originales. El espacio se mide antes de esta fase.
- B+ usa archivos y flush; el hash opera en memoria y no persiste snapshots
  durante el experimento. Ninguno fuerza fsync. No se vacía la caché del SO.
- Se realiza **una corrida por tamaño**: es un experimento descriptivo, sin
  intervalos de confianza ni garantías de repetibilidad de los tiempos. La
  semilla reproduce datos y consultas, no el ruido del sistema.

## Espacio y valores NA

No se mezcla RAM con disco en una sola curva:

| Columna | Interpretación |
| --- | --- |
| `espacio_disco_bytes` | Archivo B+ completo; incluye registros en el agrupado. Hash: NA (no persistido). |
| `espacio_adicional_disco_bytes` | Agrupado: archivo menos N × 36 B de registros; no agrupado: archivo completo. Incluye páginas, claves, punteros y holgura. |
| `memoria_estimada_bytes` | Grafo Python retenido por el hash, con `sys.getsizeof` y referencias contadas una vez. Incluye claves y RIDs; no equivale a RSS ni memoria pico. B+: NA (no medida). |
| `tiempo_rango_seg` | Hash: NA porque no soporta rangos; no representa tiempo cero. |
| `tiempo_reorganizacion_seg` | Heap: NA porque no tiene esa operación. |

`*_metadata.json` registra entorno, versión de Python/matplotlib, configuración,
cantidad de operaciones, estadísticas estructurales y duración completa. Los PNG
usan X logarítmico; los tiempos también usan Y logarítmico para mostrar técnicas
con diferencias grandes. Las conclusiones reales se recogen en `docs/informe.md`.
