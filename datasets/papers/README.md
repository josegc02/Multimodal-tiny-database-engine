# Corpus de papers académicos — opción A (RAG), issue #97

Colección de 100–300 papers de arXiv sobre bases de datos y recuperación de
información (HNSW y ANN por grafos, IVF/FAISS y cuantización, LSH, bases de
datos vectoriales, BM25 e índice invertido, recuperación densa y dispersa,
RAG, R-Tree e índices espaciales, índices aprendidos, B+/LSM/hashing,
optimización de consultas), más material del curso opcional. El texto se
corta en fragmentos de 200–500 palabras con su página de origen y se carga
en el motor en dos tablas con índice SPIMI en inglés.

## Pipeline

Desde la raíz del repositorio, con `requirements.txt` instalado (añade `pypdf`):

```sh
# 1. Elegir papers (una sola vez; ~15 min por la pausa de 3 s de la API)
python -m rag.arxiv seleccionar --maximo 250
git add -f datasets/papers/seleccion.csv          # la lista congelada se versiona

# 2. Descargar los PDFs de esa lista (idempotente: reanuda si se corta)
python -m rag.arxiv descargar

# 3. Extraer texto, fragmentar y generar CSV + SQL
python -m rag.corpus construir

# 4a. Cargar en un motor persistente (carpeta de la API, data/app)
python -m rag.corpus cargar --datos data/app
# 4b. …o pegar datasets/papers/generated/cargar_motor.sql en la interfaz
```

| Archivo | Versionado | Contenido |
|---|---|---|
| `seleccion.csv` | **sí** (`git add -f`) | arxiv_id, versión, título, autores, año, abstract, categoría, URL del PDF, licencia, tema de búsqueda |
| `pdf/` | no | PDFs descargados (`<arxiv_id>.pdf`, `/` → `_` en IDs antiguos) |
| `curso/` | no | material del curso + `curso.csv` (ver abajo) |
| `generated/papers.csv`, `generated/fragmentos.csv` | no | datos listos para `COPY` |
| `generated/cargar_motor.sql` | no | `CREATE TABLE` + `COPY` + `CREATE INDEX … USING SPIMI` |
| `generated/metadata.json` | no | parámetros, conteos, distribución de palabras, SHA-256 |

`construir` exige un directorio de salida nuevo: para regenerar, borrar
`generated/` o usar `--salida`. Mientras `seleccion.csv` no cambie, los IDs
de `papers` y `fragmentos` son los mismos en cada corrida.

## Selección (`rag/arxiv.py`)

- **Semillas**: 23 papers fundamentales fijados por ID (HNSW, FAISS, NSG,
  ScaNN, learned index, RAG, DPR, ColBERT/v2, ANCE, REALM, FiD, RETRO,
  Contriever, SPLADE, BEIR, MS MARCO, Sentence-BERT, HyDE, Lost in the
  Middle, Self-RAG, survey de RAG…). Si alguno no existe, se avisa.
- **Temas**: 12 búsquedas fijas en `cs.DB`, `cs.IR`, `cs.DS` (y `cs.CL`,
  `cs.LG`, `cs.CV`, `cs.CG` según el tema), ordenadas por relevancia.
- Los resultados se intercalan tema por tema (round-robin) hasta `--maximo`,
  para que ningún tema acapare el corpus; los duplicados se descartan.
- Se guarda la **versión** exacta (`v4`…): `descargar` baja siempre ese PDF.

## Fragmentación (`rag/chunking.py`)

- Extracción por página con `pypdf`; normalización NFKC (ligaduras `ﬁ`),
  unión de palabras partidas por guion al final de línea.
- Se recorta la bibliografía (último encabezado *References* en la segunda
  mitad del documento). Se pierden los apéndices posteriores; desactivar
  con `--con-referencias`.
- Un fragmento se cierra en el primer fin de oración a partir de 350
  palabras, o a la fuerza en 500. Un resto menor a 200 se une al anterior o
  se reparte en dos mitades. Solo un documento entero de menos de 200
  palabras produce un fragmento menor (`metadata.json` → `bajo_minimo`).
- `pagina` es la página donde empieza el fragmento y `pagina_fin` donde
  termina (numeradas desde 1, como en el visor de PDF).
- Sin solapamiento entre fragmentos.

## Esquema en el motor

```sql
CREATE TABLE papers (id INT PRIMARY KEY, arxiv_id TEXT, titulo TEXT, autores TEXT,
  anio INT, abstract TEXT, categoria TEXT, fuente TEXT, url TEXT, licencia TEXT, tema TEXT);
CREATE TABLE fragmentos (id INT PRIMARY KEY, paper_id INT REFERENCES papers(id),
  orden INT, pagina INT, pagina_fin INT, palabras INT, texto TEXT);
CREATE INDEX fragmentos_texto ON fragmentos (texto) USING SPIMI WITH (LANGUAGE = 'en');
```

`fuente` es `arxiv` o `curso`. Ejemplo de recuperación con cita. El motor
solo admite `MATCH` en un `SELECT` sobre una sola tabla (sin `JOIN`), así
que el título se busca en una segunda consulta:

```sql
SELECT paper_id, pagina, SCORE() AS s FROM fragmentos
WHERE MATCH(texto, 'hierarchical navigable small world graph') USING BM25
ORDER BY s DESC LIMIT 5;

SELECT titulo, url FROM papers WHERE id = 1;  -- con cada paper_id obtenido
```

Las rutas de `COPY` son relativas a la raíz del repo cuando la salida está
dentro de él (el motor resuelve `COPY` contra esa raíz), así que el SQL
funciona en cualquier clon.

## Material del curso

Copiar los PDFs a `datasets/papers/curso/` y describirlos en
`datasets/papers/curso/curso.csv`:

```csv
archivo,titulo,autores,anio,categoria,licencia
ppt09_indice_invertido.pdf,PPT 09: Índice invertido,Docente del curso,2026,curso,Material de clase (uso interno)
```

Se agregan después de los papers de arXiv con `fuente = 'curso'`. No se
versionan ni se redistribuyen.

## Licencias y fuentes

- Metadata: API de arXiv (<https://info.arxiv.org/help/api/>). *Thank you
  to arXiv for use of its open access interoperability.*
- La columna `licencia` de cada paper viene de OAI-PMH (formato `arXiv`).
  La mayoría usa la licencia no exclusiva de arXiv
  (`http://arxiv.org/licenses/nonexclusive-distrib/1.0/`), que **no permite
  redistribuir** el PDF; otros son CC BY, CC BY-SA, CC0, etc.
- Por eso el repositorio solo versiona la lista (`seleccion.csv`) y los
  scripts; PDFs, textos y fragmentos se regeneran localmente. Los derechos
  de cada paper son de sus autores.
- Uso acotado a un proyecto académico; se respeta el límite de una petición
  cada 3 segundos.

## Pruebas

```sh
python -m pytest -q tests/test_papers_corpus.py
```

No usan la red: la API se simula y los PDFs se generan en la prueba.