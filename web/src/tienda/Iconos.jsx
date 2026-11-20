// Íconos de contorno a 1.5 px en el color del texto; la marca de Partida.
const base = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, 'aria-hidden': true };

export const IconoBuscar = () => (
  <svg {...base} width="14" height="14" viewBox="0 0 14 14"><circle cx="6" cy="6" r="4.5" /><path d="M9.5 9.5 13 13" strokeLinecap="round" /></svg>
);
export const IconoError = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" role="img" aria-label="Error" style={{ flex: 'none', marginTop: 2 }}>
    <circle cx="8" cy="8" r="7" fill="none" stroke="var(--negativo)" strokeWidth="1.5" />
    <path d="M8 4.5v4.2M8 10.8v.7" stroke="var(--negativo)" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
export const IconoUbicacion = () => (
  <svg {...base} width="14" height="14" viewBox="0 0 14 14"><path d="M7 13s4.5-4.2 4.5-7.5a4.5 4.5 0 0 0-9 0C2.5 8.8 7 13 7 13Z" /><circle cx="7" cy="5.5" r="1.6" /></svg>
);

/** La marca: una "P" que es también un mando visto de lado, con el botón en el tono. */
export const Marca = ({ tamano = 28 }) => (
  <svg width={tamano} height={tamano} viewBox="0 0 24 24" role="img" aria-label="Partida">
    <rect width="24" height="24" rx="6" fill="var(--tinta)" />
    <path d="M7 7.5h6.2a3.3 3.3 0 0 1 0 6.6H9.6v2.4H7z" fill="var(--blanco)" />
    <circle cx="16.5" cy="16.5" r="1.6" fill="var(--tono-claro)" />
  </svg>
);
