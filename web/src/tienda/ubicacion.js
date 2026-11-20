// Dónde está quien compra: por defecto, UTEC en Barranco; o la del navegador si la comparte.
export const UTEC = { lat: -12.1352, lon: -77.0222, nombre: 'UTEC, Barranco' };
const CLAVE = 'partida.ubicacion';

export function leerUbicacion() {
  try {
    const guardada = JSON.parse(localStorage.getItem(CLAVE) ?? 'null');
    return guardada && Number.isFinite(guardada.lat) && Number.isFinite(guardada.lon) ? guardada : UTEC;
  } catch { return UTEC; }
}

export function guardarUbicacion(ubicacion) {
  try { localStorage.setItem(CLAVE, JSON.stringify(ubicacion)); } catch { /* se usa solo en esta visita */ }
}

/** Promesa con la ubicación del navegador, o un error en palabras. */
export const pedirUbicacion = () => new Promise((resolver, rechazar) => {
  if (!navigator.geolocation) { rechazar(new Error('Este navegador no comparte la ubicación.')); return; }
  navigator.geolocation.getCurrentPosition(
    (p) => resolver({ lat: p.coords.latitude, lon: p.coords.longitude, nombre: 'tu ubicación' }),
    () => rechazar(new Error('No se pudo obtener tu ubicación; seguimos con la anterior.')),
    { timeout: 8000, maximumAge: 600000 },
  );
});
