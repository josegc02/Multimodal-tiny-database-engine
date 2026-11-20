// Vistos recientemente: solo en este navegador (comodidad, no estado que deba persistir).
const CLAVE = 'partida.vistos';
const MAX = 12;

export function leerVistos() {
  try { return JSON.parse(localStorage.getItem(CLAVE) ?? '[]'); } catch { return []; }
}

export function guardarVisto(producto) {
  const lista = [{ id: producto.id, titulo: producto.titulo, imagen: producto.imagen, precio: producto.precio },
    ...leerVistos().filter((v) => v.id !== producto.id)].slice(0, MAX);
  try { localStorage.setItem(CLAVE, JSON.stringify(lista)); } catch { /* sin almacenamiento: no se recuerda */ }
  return lista;
}
