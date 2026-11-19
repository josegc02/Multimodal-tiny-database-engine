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

## Pantallas

| Ruta | Qué hace |
| --- | --- |
| `#/asistente` | Preguntar: respuesta con citas `[n]`, fuentes con su página y puntaje BM25, y "Cómo se respondió" (palabras clave, el SQL real y los tiempos) |
| `#/asistente/p/<pregunta>` | Abre y pregunta de inmediato; sirve para preparar enlaces de la demo |
| `#/asistente/biblioteca` | Los 259 documentos, con búsqueda y filtros por tipo y tema |
| `#/asistente/documento/<id>` | Un documento: abstract, fragmentos y enlaces al PDF en cada página |
| `#/asistente/subir` | Sube un PDF: lo extrae, lo fragmenta y lo indexa en el motor |

Las preguntas recientes se guardan en el navegador con su respuesta, así que volver a una no gasta cuota del LLM.

Si el LLM falla (sin key, sin cuota o sin internet), la respuesta ofrece **"Responder solo con fragmentos"**, que pregunta con `usar_llm: false`.

## Diseño

Estilo *achromatic ledger* de la skill `design-taste-frontend` (pantalla de aplicación): la interfaz va en tinta y el único color, el azul `--dato`, marca las citas y la fuente seleccionada. Las variables están en `src/estilos.css`. La maqueta aprobada por el equipo está en el canvas del proyecto.

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
