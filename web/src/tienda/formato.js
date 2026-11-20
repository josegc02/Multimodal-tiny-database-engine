// Precios en dólares, como en Amazon; cifras con separador de miles y dígitos tabulares.
const dolares = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const entero = new Intl.NumberFormat('en-US');
const decimal = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const precio = (n) => (n == null || Number.isNaN(Number(n)) ? '—' : dolares.format(n));
export const cantidad = (n) => (n == null ? '—' : entero.format(n));
export const estrellas = (n) => (n == null ? '—' : decimal.format(n));
export const distancia = (m) => (m == null ? '—' : m < 1000 ? `${Math.round(m)} m` : `${decimal.format(m / 1000)} km`);
/** Título editorial: el nombre antes de la primera coma, guion o paréntesis (los de Amazon
 *  traen la ficha técnica en el título), cortado en una palabra hacia los 70 caracteres. */
export function tituloCorto(titulo = '') {
  const corte = titulo.split(/,| - | – | \| | \(|【|\[/)[0].trim();
  const base = corte.length >= 15 ? corte : titulo;
  if (base.length <= 70) return base;
  return `${base.slice(0, 70).replace(/\s+\S*$/, '')}…`;
}

export const plural = (n, uno, varios) => `${cantidad(n)} ${n === 1 ? uno : varios}`;
