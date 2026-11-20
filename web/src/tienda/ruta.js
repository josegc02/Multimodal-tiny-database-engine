import { useEffect, useState } from 'react';

// Rutas por hash; los filtros viven en la URL para poder compartir o volver a una búsqueda.
//   #/?q=mando&c=Video%20Games%20%3E%20PlayStation%204&min=10&max=50   catálogo
//   #/p/<id>                                                          ficha de un producto
//   #/p/<id>/explicar                                                 la ficha con "Explicar y ajustar" abierto
//   #/vistos                                                          vistos recientemente
export function leerRuta(hash = window.location.hash) {
  const [camino, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const partes = camino.split('/').filter(Boolean);
  if (partes[0] === 'p' && /^\d+$/.test(partes[1] ?? '')) return { vista: 'ficha', id: Number(partes[1]), explicar: partes[2] === 'explicar' };
  if (partes[0] === 'vistos') return { vista: 'vistos' };
  const p = new URLSearchParams(query);
  return { vista: 'catalogo', q: p.get('q') ?? '', categoria: p.get('c') ?? '', min: p.get('min') ?? '', max: p.get('max') ?? '' };
}

export const enlace = {
  catalogo: ({ q, categoria, min, max } = {}) => {
    const p = new URLSearchParams();
    if (q) p.set('q', q);
    if (categoria) p.set('c', categoria);
    if (min) p.set('min', min);
    if (max) p.set('max', max);
    const texto = p.toString();
    return texto ? `#/?${texto}` : '#/';
  },
  ficha: (id, explicar = false) => `#/p/${id}${explicar ? '/explicar' : ''}`,
  vistos: '#/vistos',
};

export const ir = (destino) => { window.location.hash = destino; };

export function useRuta() {
  const [ruta, setRuta] = useState(() => leerRuta());
  useEffect(() => {
    const cambiar = () => setRuta(leerRuta());
    window.addEventListener('hashchange', cambiar);
    return () => window.removeEventListener('hashchange', cambiar);
  }, []);
  return ruta;
}
