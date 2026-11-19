// Preguntas recientes de este navegador. Se guarda la respuesta completa, así
// volver a una pregunta no gasta cuota del LLM. localStorage puede fallar
// (modo privado, almacenamiento bloqueado): entonces el historial solo vive en memoria.
const CLAVE = 'bd2.asistente.recientes';
const MAXIMO = 30;
let enMemoria = null;

export function leerRecientes() {
  if (enMemoria) return enMemoria;
  try {
    const guardado = JSON.parse(window.localStorage.getItem(CLAVE) ?? '[]');
    return Array.isArray(guardado) ? guardado : [];
  } catch {
    return [];
  }
}

export function guardarReciente(datos) {
  const anteriores = leerRecientes();
  const id = anteriores.find((r) => r.pregunta === datos.pregunta)?.id ?? Date.now().toString(36);
  const lista = [{ id, pregunta: datos.pregunta, datos }, ...anteriores.filter((r) => r.id !== id)]
    .slice(0, MAXIMO);
  enMemoria = lista;
  try {
    window.localStorage.setItem(CLAVE, JSON.stringify(lista));
  } catch {
    // sin almacenamiento: queda en memoria
  }
  return { id, lista };
}
