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
      'No se pudo conectar con el servidor. Revisa la conexión y vuelve a intentarlo.');
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
