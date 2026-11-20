import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { distancia } from './formato.js';

const color = (nombre) => getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();

/** Tú y las tiendas con stock; la más cercana, más grande. Los mosaicos son de OpenStreetMap. */
export default function Mapa({ ubicacion, tiendas, cercanaId }) {
  const nodo = useRef(null);
  const mapa = useRef(null);
  const capa = useRef(null);

  useEffect(() => {
    mapa.current = L.map(nodo.current, { scrollWheelZoom: false, zoomControl: true, attributionControl: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '© colaboradores de OpenStreetMap',
    }).addTo(mapa.current);
    capa.current = L.layerGroup().addTo(mapa.current);
    return () => mapa.current.remove();
  }, []);

  useEffect(() => {
    if (!mapa.current) return;
    capa.current.clearLayers();
    const tono = color('--tono');
    const tinta = color('--tinta');
    const puntos = [[ubicacion.lat, ubicacion.lon]];
    L.circleMarker([ubicacion.lat, ubicacion.lon], { radius: 7, color: color('--blanco'), weight: 2, fillColor: tinta, fillOpacity: 1 })
      .bindTooltip(`Tú: ${ubicacion.nombre}`).addTo(capa.current);
    for (const t of tiendas) {
      const cercana = t.id === cercanaId;
      L.circleMarker([t.ubicacion.lat, t.ubicacion.lon], {
        radius: cercana ? 9 : 6, color: color('--blanco'), weight: 2, fillColor: tono, fillOpacity: cercana ? 1 : 0.75,
      }).bindTooltip(`${t.nombre}: ${distancia(t.distancia_m)}, ${t.unidades} en stock`).addTo(capa.current);
      puntos.push([t.ubicacion.lat, t.ubicacion.lon]);
    }
    if (puntos.length > 1) mapa.current.fitBounds(puntos, { padding: [28, 28], maxZoom: 15 });
    else mapa.current.setView(puntos[0], 13);
  }, [ubicacion, tiendas, cercanaId]);

  return <div ref={nodo} className="mapa" role="region" aria-label="Mapa de tu ubicación y las tiendas con stock" />;
}
