// Las consolas son el segundo nivel de la categoría de Amazon ("Video Games > PlayStation 4").
// Las cinco con más productos van como tarjetas; el resto, en "Otra consola".
export const RAIZ = 'Video Games';
export const NOMBRES = {
  'Legacy Systems': 'Consolas clásicas',
  'Xbox Series X & S': 'Xbox Series X|S',
  'Virtual Reality': 'Realidad virtual',
  'Video Games Accessories': 'Accesorios',
};
export const nombre = (segmento) => NOMBRES[segmento] ?? segmento;

const dentro = (categoria, prefijo) => categoria === prefijo || categoria.startsWith(`${prefijo} > `);

/** [{categoria, productos}] → consolas {categoria, nombre, productos} de mayor a menor. */
export function consolas(categorias) {
  const suma = new Map();
  for (const { categoria, productos } of categorias) {
    const partes = (categoria ?? '').split(' > ');
    if (partes[0] !== RAIZ || partes.length < 2) continue;
    const clave = `${RAIZ} > ${partes[1]}`;
    suma.set(clave, (suma.get(clave) ?? 0) + productos);
  }
  return [...suma].map(([categoria, productos]) => ({ categoria, nombre: nombre(categoria.split(' > ')[1]), productos }))
    .sort((a, b) => b.productos - a.productos || a.nombre.localeCompare(b.nombre));
}

/** Los tipos dentro de una consola (tercer nivel): "Games", "Accessories"... con su cantidad. */
export function tipos(categorias, consola) {
  if (!consola) return [];
  const nivel = consola.split(' > ').length;
  const suma = new Map();
  for (const { categoria, productos } of categorias) {
    if (!categoria || !dentro(categoria, consola) || categoria === consola) continue;
    const clave = categoria.split(' > ').slice(0, nivel + 1).join(' > ');
    suma.set(clave, (suma.get(clave) ?? 0) + productos);
  }
  return [...suma].map(([categoria, productos]) => ({ categoria, nombre: categoria.split(' > ').at(-1), productos }))
    .sort((a, b) => b.productos - a.productos);
}

/** La consola de una categoría completa, y si la categoría es más específica que la consola. */
export const consolaDe = (categoria) => (categoria ? categoria.split(' > ').slice(0, 2).join(' > ') : '');

/** Cantidad de productos dentro de un prefijo de categoría. */
export const contar = (categorias, prefijo) =>
  categorias.reduce((n, c) => (!prefijo || (c.categoria && dentro(c.categoria, prefijo)) ? n + c.productos : n), 0);
