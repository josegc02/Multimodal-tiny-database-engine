import { useState } from 'react';
import { tienda } from '../api.js';

/** La foto guardada junto al motor; si no carga, la de Amazon; si tampoco, un recuadro vacío. */
export default function Foto({ producto, alt = '', prioridad = false }) {
  const fuentes = [producto.imagen && tienda.urlImagen(producto.imagen), producto.url_imagen].filter(Boolean);
  const [indice, setIndice] = useState(0);
  if (indice >= fuentes.length) return <span className="gris" style={{ fontSize: 12 }}>Sin foto</span>;
  return <img src={fuentes[indice]} alt={alt} loading={prioridad ? 'eager' : 'lazy'} fetchpriority={prioridad ? 'high' : 'auto'} decoding="async" onError={() => setIndice(indice + 1)} />;
}
