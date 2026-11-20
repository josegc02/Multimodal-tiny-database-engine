import { useEffect, useState } from 'react';

// Rutas por hash, para servir el front como archivos estáticos sin configurar nada:
//   #/asistente               Preguntar
//   #/asistente/r/<id>        una pregunta reciente
//   #/asistente/p/<pregunta>  pregunta al abrir (enlaces para la demo)
//   #/asistente/biblioteca    Biblioteca
//   #/asistente/documento/<n> detalle de un documento
//   #/asistente/subir         Subir PDF
export function leerRuta(hash = window.location.hash) {
  const [camino, consulta = ''] = hash.split('?');
  const filtros = new URLSearchParams(consulta);
  const partes = camino.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (partes[0] !== 'asistente') return { vista: 'preguntar' };
  if (partes[1] === 'biblioteca') return { vista: 'biblioteca', filtros };
  if (partes[1] === 'subir') return { vista: 'subir' };
  if (partes[1] === 'documento' && /^\d+$/.test(partes[2] ?? '')) return { vista: 'documento', id: Number(partes[2]), filtros };
  if (partes[1] === 'r' && partes[2]) return { vista: 'preguntar', reciente: partes[2] };
  if (partes[1] === 'p' && partes[2]) return { vista: 'preguntar', auto: decodeURIComponent(partes.slice(2).join('/')) };
  return { vista: 'preguntar' };
}

export const enlace = {
  preguntar: '#/asistente',
  reciente: (id) => `#/asistente/r/${id}`,
  preguntarYa: (texto) => `#/asistente/p/${encodeURIComponent(texto)}`,
  biblioteca: '#/asistente/biblioteca',
  documento: (id, filtros) => conFiltros(`#/asistente/documento/${id}`, filtros),
  subir: '#/asistente/subir',
};

export function conFiltros(destino, filtros) {
  const consulta = filtros?.toString();
  return consulta ? `${destino}?${consulta}` : destino;
}

export function ir(destino) {
  window.location.hash = destino;
}

export function useRuta() {
  const [ruta, setRuta] = useState(() => leerRuta());
  useEffect(() => {
    const cambiar = () => setRuta(leerRuta());
    window.addEventListener('hashchange', cambiar);
    return () => window.removeEventListener('hashchange', cambiar);
  }, []);
  function reemplazar(destino) {
    window.history.replaceState(window.history.state, '', destino);
    setRuta(leerRuta());
  }
  return [ruta, reemplazar];
}
