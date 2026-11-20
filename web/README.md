# Front web (Parte 5)

Vite + React, con **dos apps en el mismo proyecto**, cada una con su armazón e identidad, que comparten
el cliente de la API (`src/api.js`):

| App | Página | Código |
| --- | --- | --- |
| Asistente académico (opción A, #99) | `http://localhost:5173/` | `index.html`, `src/` |
| **Partida**, la tienda de videojuegos (opción B, #103) | `http://localhost:5173/tienda.html` | `tienda.html`, `src/tienda/` |

`npm run dev` levanta las dos; `npm run build` genera las dos en `dist/`.

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


## Tienda: Partida

Necesita la tienda cargada en la carpeta de datos de la API (`tienda.amazon compras`, `tienda.carga preparar`,
`tienda.carga cargar` y `tienda.indice_imagen`; ver `datasets/tienda/README.md`). Con la tienda completa la API
tarda ~6 minutos en arrancar: levántala antes de la demo.

| Ruta | Qué hace |
| --- | --- |
| `#/` | Catálogo: búsqueda BM25 en la barra superior, tarjetas por consola con su cantidad (filtran), tipo y precio; los filtros viven en la URL (`#/?q=...&c=...&min=...&max=...`) |
| `#/p/<id>` | Ficha: el producto, la tienda más cercana con stock y el mapa (desde UTEC, o la ubicación del navegador), y "Te puede interesar": las 10 recomendaciones con su motivo. "Explicar y ajustar" muestra cuánto aportó cada señal y deja mover los pesos y cambiar entre MobileNet y SIFT: la lista se reordena en vivo y marca cuánto subió o bajó cada producto |
| `#/vistos` | Los últimos productos abiertos en este navegador |

Las fotos se sirven desde la API (`GET /archivos`); si una no carga, se usa la de Amazon. El mapa usa
Leaflet con mosaicos de OpenStreetMap (necesita internet).

Diseño: estilo *framed sheet* de `design-taste-frontend` (pantalla de aplicación): un marco gris verdoso con
la barra superior y el trabajo en una hoja blanca; el único tono, el verde azulado `--tono`, marca el dato
principal (la distancia a la tienda, la señal que más aportó) y la selección. Tipografía IBM Plex Sans.
Variables en `src/tienda/estilos.css`. Revisado también con las reglas de suelo de hallmark.
