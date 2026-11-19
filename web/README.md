# Front web (Parte 5)

Vite + React. Por ahora tiene el **asistente académico** (opción A, #99); la tienda (opción B, #103) se agrega sobre la misma base.

## Levantarlo

Necesita la API corriendo con el corpus cargado (ver `docs/api.md` y `datasets/papers/README.md`):

```bash
# terminal 1, desde la raíz del repositorio
python -m rag.corpus cargar --datos data/app     # una sola vez
uvicorn api.main:app                             # con GEMINI_API_KEY definida

# terminal 2
cd web
npm install                                      # una sola vez
npm run dev                                      # http://localhost:5173
```

La API se busca en `http://127.0.0.1:8000`; para otra dirección, crea `web/.env.local` con `VITE_API_URL=http://...`.

Para la exposición, `VITE_TRAZA_ABIERTA=1` deja abierto por defecto el panel "Cómo se respondió" (sin la variable, cada navegador recuerda si lo abrió).

## Pantallas

| Ruta | Qué hace |
| --- | --- |
| `#/asistente` | Preguntar: respuesta con citas `[n]` (con vista previa de la fuente al pasar el mouse) y los documentos en que se basa; fuentes con su página, su puntaje BM25 y las palabras clave resaltadas; y "Cómo se respondió", plegable: el flujo en 4 pasos, el gráfico de los candidatos de BM25 (elegidos y por qué se descartó el resto), dónde se fue el tiempo y el SQL real |
| `#/asistente/p/<pregunta>` | Abre y pregunta de inmediato; sirve para preparar enlaces de la demo |
| `#/asistente/biblioteca` | Los documentos cargados, con búsqueda por título y filtros por año, autor, tipo y tema |
| `#/asistente/documento/<id>` | Un documento: abstract, fragmentos y enlaces al PDF en cada página |
| `#/asistente/subir` | Sube un PDF: lo extrae, lo fragmenta y lo indexa en el motor |

Las preguntas recientes se guardan en el navegador con su respuesta, así que volver a una no gasta cuota del LLM.

Si el LLM falla (sin key, sin cuota o sin internet), la respuesta ofrece **"Buscar solo fragmentos"**, que pregunta con `usar_llm: false`.

## Diseño

La vista de consulta prioriza la pregunta, la lectura y la verificación de fuentes. Usa Spectral para los títulos, Geist para los controles y un acento violeta que identifica la cita y su fragmento. En móvil las fuentes se presentan después de la respuesta. Los detalles de BM25, SPIMI y SQL siguen disponibles en «Cómo se respondió».

## Estructura

```
src/
  api.js          cliente de la API (errores con su estado HTTP)
  ruta.js         rutas por hash
  historial.js    preguntas recientes en localStorage
  formato.js      referencias, páginas, temas y limpieza de fragmentos
  estilos.css     variables y componentes
  App.jsx         barra lateral y vistas
  asistente/      Preguntar, Fuentes, Traza, Biblioteca, Documento, Subir
```
