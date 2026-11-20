// Cliente de la API REST del motor (api/main.py, contrato en docs/api.md).
export const BASE = (import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');

export class ErrorApi extends Error {
  constructor(estado, mensaje) {
    super(mensaje);
    this.estado = estado; // número HTTP, o 'sin_conexion'
  }
}

async function pedir(ruta, opciones = {}) {
  let respuesta;
  try {
    respuesta = await fetch(BASE + ruta, opciones);
  } catch {
    throw new ErrorApi('sin_conexion',
      `La API no responde en ${BASE}. Levántala desde la raíz del proyecto con: uvicorn api.main:app`);
  }
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    const detalle = Array.isArray(datos.detail) ? datos.detail.map((d) => d.msg).join('; ') : datos.detail;
    throw new ErrorApi(respuesta.status, datos.error || detalle || `Error ${respuesta.status}`);
  }
  return datos;
}

const json = (cuerpo) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(cuerpo),
});

export const api = {
  estado: () => pedir('/asistente/estado'),
  preguntar: ({ pregunta, k = 5, usarLlm = true }) =>
    pedir('/asistente/preguntar', json({ pregunta, k, usar_llm: usarLlm })),
  documentos: () => pedir('/asistente/documentos'),
  documento: (id) => pedir(`/asistente/documentos/${id}`),
  subir: (formulario) => pedir('/asistente/documentos', { method: 'POST', body: formulario }),
  urlPdf: (id, pagina) => `${BASE}/asistente/documentos/${id}/pdf${pagina ? `#page=${pagina}` : ''}`,
};

// ---- Tienda (opción B): contrato en docs/api.md ----
const consulta = (parametros) => {
  const q = new URLSearchParams();
  for (const [clave, valor] of Object.entries(parametros)) {
    if (valor !== undefined && valor !== null && valor !== '') q.set(clave, valor);
  }
  const texto = q.toString();
  return texto ? `?${texto}` : '';
};

export const tienda = {
  categorias: () => pedir('/categorias'),
  catalogo: ({ q, categoria, precioMin, precioMax, limite = 24, offset = 0 } = {}) =>
    pedir(`/catalogo${consulta({ q, categoria, precio_min: precioMin, precio_max: precioMax, limite, offset })}`),
  producto: (id, ubicacion) => pedir(`/productos/${id}${consulta({ lat: ubicacion?.lat, lon: ubicacion?.lon })}`),
  recomendaciones: (id, { pesos, pesoCategoria, pesoPlataforma, vectorImagen, fusion } = {}) =>
    pedir(`/recomendaciones/${id}${consulta({
      pesos: pesos?.join(','), peso_categoria: pesoCategoria, peso_plataforma: pesoPlataforma,
      vector_imagen: vectorImagen, fusion,
    })}`),
  tiendasCercanas: ({ lat, lon, productoId, limite = 8 }) =>
    pedir(`/tiendas/cercanas${consulta({ lat, lon, producto_id: productoId, limite })}`),
  // Las fotos viven en disco junto al motor; la API las sirve desde sus carpetas permitidas.
  urlImagen: (ruta) => `${BASE}/archivos${consulta({ ruta })}`,
};
