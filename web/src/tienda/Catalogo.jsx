import { useEffect, useState } from 'react';
import { tienda } from '../api.js';
import { cantidad, estrellas, plural, precio } from './formato.js';
import { consolaDe, consolas, contar, tipos } from './consolas.js';
import Foto from './Foto.jsx';
import { IconoError } from './Iconos.jsx';
import { enlace, ir } from './ruta.js';

const POR_PAGINA = 24;
const TARJETAS = 5; // consolas con tarjeta propia; el resto va en "Otra consola"

export default function Catalogo({ ruta, categorias, errorCategorias, reintentar }) {
  const { q, categoria, min, max } = ruta;
  const [filas, setFilas] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [hayMas, setHayMas] = useState(false);
  const [precioMin, setPrecioMin] = useState(min);
  const [precioMax, setPrecioMax] = useState(max);
  useEffect(() => { setPrecioMin(min); setPrecioMax(max); }, [min, max]);

  const pedir = (offset) => {
    setCargando(true);
    setError(null);
    return tienda.catalogo({ q, categoria, precioMin: min, precioMax: max, limite: POR_PAGINA, offset })
      .then((nuevas) => {
        setFilas((previas) => (offset === 0 ? nuevas : [...(previas ?? []), ...nuevas]));
        setHayMas(nuevas.length === POR_PAGINA);
      })
      .catch(setError)
      .finally(() => setCargando(false));
  };
  useEffect(() => { setFilas(null); pedir(0); }, [q, categoria, min, max]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtrar = (cambios) => ir(enlace.catalogo({ q, categoria, min, max, ...cambios }));
  const lista = categorias ? consolas(categorias) : [];
  const consola = consolaDe(categoria);
  const conTarjeta = lista.slice(0, TARJETAS);
  const otras = lista.slice(TARJETAS);
  const deConsola = categorias ? tipos(categorias, consola) : [];
  const total = categorias ? contar(categorias, categoria) : null;
  const sinFiltroDePrecio = !min && !max;
  const nombreConsola = lista.find((c) => c.categoria === consola)?.nombre;

  const titulo = q ? `Resultados para “${q}”` : (nombreConsola ?? 'Catálogo');
  const sub = q
    ? 'Ordenados por relevancia BM25 sobre la descripción, con el índice SPIMI del motor.'
    : total != null ? `${plural(total, 'producto', 'productos')} de Amazon, categoría Video Games.` : 'Productos de Amazon, categoría Video Games.';

  let resumen = '';
  if (filas) {
    resumen = !q && sinFiltroDePrecio && total != null
      ? `Mostrando ${cantidad(filas.length)} de ${cantidad(total)}`
      : `${plural(filas.length, 'resultado', 'resultados')}${hayMas ? ' hasta ahora' : ''}`;
  }

  return (
    <div className="pagina">
      <div className="titulo-fila">
        <div className="titulo-texto">
          <h1>{titulo}</h1>
          <p className="gris">{sub}</p>
        </div>
        {(q || categoria || min || max) && <button className="btn2" onClick={() => ir(enlace.catalogo())}>Quitar filtros</button>}
      </div>

      {errorCategorias && (
        <div className="error" role="alert">
          <IconoError />
          <div><strong>No se pudieron cargar las consolas.</strong> <span className="gris">{errorCategorias.message}</span></div>
          <button className="enlace" onClick={reintentar} style={{ marginLeft: 'auto' }}>Reintentar</button>
        </div>
      )}

      <div className="consolas" role="group" aria-label="Consola">
        <Consola nombre="Todas" productos={categorias ? contar(categorias, '') : null} activa={!consola}
                 alElegir={() => filtrar({ categoria: '' })} />
        {conTarjeta.map((c) => (
          <Consola key={c.categoria} nombre={c.nombre} productos={c.productos} activa={consola === c.categoria}
                   alElegir={() => filtrar({ categoria: c.categoria })} />
        ))}
        {!categorias && !errorCategorias && Array.from({ length: TARJETAS }, (_, i) => (
          <div key={i} className="consola" aria-hidden="true"><span className="esqueleto" style={{ width: 90, height: 12 }} /><span className="esqueleto" style={{ width: 48, height: 16 }} /></div>
        ))}
      </div>

      <form className="filtros" onSubmit={(e) => { e.preventDefault(); filtrar({ min: precioMin, max: precioMax }); }}>
        {otras.length > 0 && (
          <label className="campo">
            Otra consola
            <select value={otras.some((c) => c.categoria === consola) ? consola : ''}
                    onChange={(e) => filtrar({ categoria: e.target.value })}>
              <option value="">Elegir</option>
              {otras.map((c) => <option key={c.categoria} value={c.categoria}>{c.nombre} ({cantidad(c.productos)})</option>)}
            </select>
          </label>
        )}
        <label className="campo">
          Tipo
          <select value={categoria !== consola ? categoria : ''} disabled={!consola || deConsola.length === 0}
                  onChange={(e) => filtrar({ categoria: e.target.value || consola })}
                  title={!consola ? 'Elige una consola para ver sus tipos' : undefined}>
            <option value="">{consola ? 'Todos' : 'Elige una consola'}</option>
            {deConsola.map((t) => <option key={t.categoria} value={t.categoria}>{t.nombre} ({cantidad(t.productos)})</option>)}
          </select>
        </label>
        <label className="campo">
          Precio desde (US$)
          <input type="number" min="0" step="1" inputMode="decimal" value={precioMin} onChange={(e) => setPrecioMin(e.target.value)} />
        </label>
        <label className="campo">
          hasta (US$)
          <input type="number" min="0" step="1" inputMode="decimal" value={precioMax} onChange={(e) => setPrecioMax(e.target.value)} />
        </label>
        <button className="btn2" type="submit">Aplicar precio</button>
        <span className="resumen num" aria-live="polite">{resumen}</span>
      </form>

      <section className="rejilla" aria-label="Productos" aria-busy={cargando}>
        {error && (
          <div className="error" role="alert">
            <IconoError />
            <div><strong>No se pudo cargar el catálogo.</strong> <span className="gris">{error.message}</span></div>
            <button className="enlace" onClick={() => pedir(filas?.length ?? 0)} style={{ marginLeft: 'auto' }}>Reintentar</button>
          </div>
        )}
        {filas?.map((p) => <Tarjeta key={p.id} producto={p} />)}
        {!filas && !error && Array.from({ length: 8 }, (_, i) => <TarjetaCargando key={i} />)}
        {filas?.length === 0 && (
          <div className="vacio">
            <span>{q ? `Ningún producto de esta selección menciona “${q}”.` : 'Ningún producto cumple estos filtros.'}</span>
            <button className="enlace" onClick={() => ir(enlace.catalogo(q ? { q } : {}))}>{q ? 'Buscar en todo el catálogo' : 'Quitar filtros'}</button>
          </div>
        )}
      </section>

      {hayMas && filas && (
        <div className="mas">
          <button className="btn2" disabled={cargando} onClick={() => pedir(filas.length)}>
            {cargando ? 'Cargando…' : `Mostrar ${POR_PAGINA} más`}
          </button>
        </div>
      )}
    </div>
  );
}

function Consola({ nombre, productos, activa, alElegir }) {
  return (
    <button type="button" className="consola" aria-pressed={activa} onClick={alElegir}>
      <span>{nombre}</span>
      <span className="num">{productos == null ? '—' : cantidad(productos)}</span>
    </button>
  );
}

function Tarjeta({ producto: p }) {
  return (
    <a className="tarjeta" href={enlace.ficha(p.id)}>
      <span className="foto"><Foto producto={p} /></span>
      <span className="tarjeta-titulo">{p.titulo}</span>
      <span className="tarjeta-precio num">{precio(p.precio)}</span>
      <span className="tarjeta-meta num">{estrellas(p.rating)} de 5, {cantidad(p.num_resenas)} reseñas</span>
    </a>
  );
}

function TarjetaCargando() {
  return (
    <div className="tarjeta" aria-hidden="true">
      <span className="foto esqueleto" style={{ border: 0 }} />
      <span className="esqueleto" style={{ height: 14, width: '90%' }} />
      <span className="esqueleto" style={{ height: 14, width: '60%' }} />
      <span className="esqueleto" style={{ height: 18, width: 64 }} />
    </div>
  );
}
