// Íconos de contorno a 1.5 px, en el color del texto.
const base = { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, 'aria-hidden': true };

export const IconoPreguntar = () => (
  <svg {...base}><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" strokeLinejoin="round" /></svg>
);
export const IconoBiblioteca = () => (
  <svg {...base}><path d="M3 2.5v11M6.5 2.5v11M10 3l3 10" strokeLinecap="round" /></svg>
);
export const IconoSubir = () => (
  <svg {...base}><path d="M8 10.5V3M5 6l3-3 3 3M3 10.5v2.5h10v-2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
);
export const IconoMenu = () => (
  <svg {...base} width={18} height={18} viewBox="0 0 18 18"><path d="M2.5 5h13M2.5 9h13M2.5 13h13" strokeLinecap="round" /></svg>
);
export const IconoBuscar = () => (
  <svg {...base} width={14} height={14} viewBox="0 0 14 14" stroke="#6b6b6b"><circle cx="6" cy="6" r="4.5" /><path d="M9.5 9.5 13 13" strokeLinecap="round" /></svg>
);
export const IconoError = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" role="img" aria-label="Error" style={{ flex: 'none', marginTop: 4 }}>
    <circle cx="8" cy="8" r="7" fill="none" stroke="#c4242a" strokeWidth="1.5" />
    <path d="M8 4.5v4.2M8 10.8v.7" stroke="#c4242a" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

/** La marca: una lista de posteo (tres barras), la del medio en el color de las citas. */
export const Marca = ({ tamano = 24 }) => (
  <svg width={tamano} height={tamano} viewBox="0 0 24 24" role="img" aria-label="Asistente BD2">
    <rect width="24" height="24" rx="6" fill="#141414" />
    <rect x="5" y="6" width="14" height="2.4" rx="1.2" fill="#fff" />
    <rect x="5" y="10.8" width="10" height="2.4" rx="1.2" fill="#8fb3ea" />
    <rect x="5" y="15.6" width="6" height="2.4" rx="1.2" fill="#fff" />
  </svg>
);
