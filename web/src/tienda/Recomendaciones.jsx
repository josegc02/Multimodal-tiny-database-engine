import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { tienda } from '../api.js';
import { precio, tituloCorto } from './formato.js';
import Foto from './Foto.jsx';
import { IconoError } from './Iconos.jsx';
import { enlace } from './ruta.js';

// Las cinco señales de GET /recomendaciones, en el orden de los pesos de la API.
const SENALES = [
  { clave: 'compras', nombre: 'Compras', motivo: 'Lo compraron juntos', ayuda: 'Quienes compraron este producto compraron también aquel, a 30 días o menos.' },
  { clave: 'imagen', nombre: 'Imagen', motivo: 'Se ve parecido', ayuda: 'Fotos parecidas según el vector de la imagen (HNSW).' },
  { clave: 'texto', nombre: 'Texto', motivo: 'Descripción parecida', ayuda: 'Descripciones parecidas según BM25 sobre el índice SPIMI.' },
  { clave: 'categoria', nombre: 'Categoría', motivo: 'Misma categoría', ayuda: 'Suma si es de la misma categoría de Amazon.' },
  { clave: 'plataforma', nombre: 'Consola', motivo: 'Misma consola', ayuda: 'Suma si es de la misma consola, cuando el producto es de una sola.' },
];
// Los valores por defecto de la API (medidos en benchmarks/tienda).
const PESOS = { compras: 1, imagen: 0.5, texto: 1, categoria: 0.25, plataforma: 0.5 };
const ESPERA_MS = 200;      // tras el último movimiento de un slider
const ATENUAR_MS = 200;     // solo se atenúa la lista si la respuesta tarda más que esto
const MOVER_MS = 240;

/** Cuánto aportó cada señal al puntaje de una fila, en partes que suman 1. */
function aportes(fila, pesos) {
  const crudos = SENALES.map((s) => (fila.senales?.[s.clave] ?? 0) * pesos[s.clave]);
  const suma = crudos.reduce((a, b) => a + b, 0) || 1;
  return crudos.map((c) => c / suma);
}

export default function Recomendaciones({ id, explicarAlAbrir = false }) {
  const [pesos, setPesos] = useState(PESOS);
  const [vector, setVector] = useState('mobilenet');
  const [explicar, setExplicar] = useState(explicarAlAbrir);
  const [filas, setFilas] = useState(null);
  const [pesosDeFilas, setPesosDeFilas] = useState(PESOS);
  const [antes, setAntes] = useState(null);      // posiciones con los pesos anteriores
  const [error, setError] = useState(null);
  const [atenuar, setAtenuar] = useState(false);
  const pedido = useRef(0);
  const actuales = useRef(null);   // las filas en pantalla, para saber cuánto se movió cada una
  const lista = useRef(null);
  const cajas = useRef(new Map());

  useEffect(() => {
    const numero = ++pedido.current;
    const atenuador = setTimeout(() => setAtenuar(true), ATENUAR_MS);
    const espera = setTimeout(() => {
      tienda.recomendaciones(id, {
        pesos: [pesos.compras, pesos.imagen, pesos.texto], pesoCategoria: pesos.categoria,
        pesoPlataforma: pesos.plataforma, vectorImagen: vector,
      }).then((nuevas) => {
        if (numero !== pedido.current) return;   // llegó tarde: ya hay un pedido más nuevo
        const previas = actuales.current;
        setAntes(previas ? new Map(previas.map((f, i) => [f.id, i])) : null);
        actuales.current = nuevas;
        setFilas(nuevas);
        setPesosDeFilas(pesos);
        setError(null);
      }).catch((e) => { if (numero === pedido.current) setError(e); })
        .finally(() => { if (numero === pedido.current) { clearTimeout(atenuador); setAtenuar(false); } });
    }, filas ? ESPERA_MS : 0);
    return () => { clearTimeout(espera); clearTimeout(atenuador); };
  }, [id, pesos, vector]); // eslint-disable-line react-hooks/exhaustive-deps

  // FLIP: cada fila parte de donde estaba y se mueve a su nuevo lugar (solo transform).
  useLayoutEffect(() => {
    if (!lista.current) return;
    const quieto = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const nuevas = new Map();
    for (const nodo of lista.current.querySelectorAll('[data-id]')) {
      const caja = nodo.getBoundingClientRect();
      nuevas.set(nodo.dataset.id, caja.top);
      const previa = cajas.current.get(nodo.dataset.id);
      if (!quieto && previa !== undefined && Math.abs(previa - caja.top) > 1) {
        nodo.animate([{ transform: `translateY(${previa - caja.top}px)` }, { transform: 'translateY(0)' }],
          { duration: MOVER_MS, easing: 'cubic-bezier(0.77, 0, 0.175, 1)' });
      }
    }
    cajas.current = nuevas;
  }, [filas, explicar]);

  const mover = (clave, valor) => setPesos((p) => ({ ...p, [clave]: valor }));
  // Para lectores de pantalla: cuántos productos cambiaron de puesto con los pesos nuevos.
  const movidos = antes && filas ? filas.filter((f, i) => antes.get(f.id) !== i).length : 0;
  const anuncio = antes && filas ? (movidos ? `Lista actualizada: ${movidos} productos cambiaron de puesto.` : 'Lista actualizada: el orden no cambió.') : '';
  const cambiado = SENALES.some((s) => pesos[s.clave] !== PESOS[s.clave]) || vector !== 'mobilenet';
  const restablecer = () => { setPesos(PESOS); setVector('mobilenet'); };

  return (
    <div className="rejilla6">
      <section className={`panel ${explicar ? 'span4' : 'span6'}`} aria-labelledby="interesa">
        <div className="panel-cabeza">
          <div className="titulo-texto">
            <h2 id="interesa">Te puede interesar</h2>
            <p className="gris">Las 10 mejores entre compras, imagen, texto, categoría y consola, sin repetir el mismo producto.</p>
          </div>
          <div className="segmentado" role="group" aria-label="Modo">
            <button type="button" aria-pressed={!explicar} onClick={() => setExplicar(false)}>Recomendaciones</button>
            <button type="button" aria-pressed={explicar} onClick={() => setExplicar(true)}>Explicar y ajustar</button>
          </div>
        </div>

        {error && (
          <div className="error" role="alert">
            <IconoError />
            <div><strong>No se pudieron calcular las recomendaciones.</strong> <span className="gris">{error.message}</span></div>
            <button className="enlace" onClick={() => setPesos((p) => ({ ...p }))} style={{ marginLeft: 'auto' }}>Reintentar</button>
          </div>
        )}
        <p className="oculto" aria-live="polite">{anuncio}</p>
        {!filas && !error && <RecsCargando />}
        {filas?.length === 0 && <p className="vacio">Ninguna señal encontró productos parecidos con estos pesos.</p>}

        {filas?.length > 0 && (
          <div>
            {explicar && (
              <div className="recs-cabeza" aria-hidden="true">
                <span /><span /><span className="gris" style={{ fontSize: 12 }}>Cuánto aportó cada señal</span><span />
                <span className="recibo-cabeza">{SENALES.map((s) => <span key={s.clave}>{s.nombre}</span>)}</span>
              </div>
            )}
            <ol className="recs" ref={lista} data-cargando={atenuar}>
              {filas.map((fila, i) => (
                <Fila key={fila.id} fila={fila} posicion={i} previa={antes?.get(fila.id)} hayAntes={antes != null}
                      partes={aportes(fila, pesosDeFilas)} explicar={explicar} />
              ))}
            </ol>
          </div>
        )}
      </section>

      {explicar && (
        <aside className="panel span2" aria-labelledby="pesos">
          <div className="panel-cabeza">
            <h2 id="pesos">Pesos</h2>
            <button className="enlace" onClick={restablecer} disabled={!cambiado}>Restablecer</button>
          </div>
          <div className="pesos">
            {SENALES.map((s) => (
              <div className="peso" key={s.clave}>
                <label htmlFor={`peso-${s.clave}`}>{s.nombre}</label>
                <output className="num" htmlFor={`peso-${s.clave}`}>{pesos[s.clave].toFixed(2)}</output>
                <input id={`peso-${s.clave}`} type="range" min="0" max="2" step="0.25" value={pesos[s.clave]}
                       onChange={(e) => mover(s.clave, Number(e.target.value))} />
                <small>{s.ayuda}</small>
              </div>
            ))}
            <div className="peso">
              <span style={{ fontWeight: 500 }}>Vector de la imagen</span>
              <div className="segmentado" role="group" aria-label="Vector de la imagen" style={{ gridColumn: '1 / -1', justifySelf: 'start' }}>
                <button type="button" aria-pressed={vector === 'mobilenet'} onClick={() => setVector('mobilenet')}>MobileNet</button>
                <button type="button" aria-pressed={vector === 'sift'} onClick={() => setVector('sift')}>SIFT</button>
              </div>
              <small>MobileNet reconoce qué es el objeto; SIFT, puntos locales de la foto.</small>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

function Fila({ fila, posicion, previa, hayAntes, partes, explicar }) {
  const fuerte = partes.indexOf(Math.max(...partes));
  const motivos = SENALES.map((s, i) => ({ ...s, parte: partes[i] }))
    .filter((s) => s.parte >= 0.15).sort((a, b) => b.parte - a.parte).slice(0, 2);
  let cambio = '';
  if (hayAntes && previa === undefined) cambio = 'Nuevo';
  else if (hayAntes && previa !== posicion) cambio = previa > posicion ? `Subió ${previa - posicion}` : `Bajó ${posicion - previa}`;

  return (
    <li className={`rec ${explicar ? 'explicando' : ''}`} data-id={fila.id}>
      <span className="rec-pos num">{posicion + 1}</span>
      <a className="rec-foto" href={enlace.ficha(fila.id)} tabIndex={-1} aria-hidden="true"><Foto producto={fila} /></a>
      <span className="rec-texto">
        <a href={enlace.ficha(fila.id)} title={fila.titulo}>{tituloCorto(fila.titulo)}</a>
        <span className="motivo">
          {motivos.map((m) => <span key={m.clave}>{m.motivo}</span>)}
          {cambio && <span className="cambio">{cambio}</span>}
        </span>
      </span>
      <span className="rec-precio num">{precio(fila.precio)}</span>
      {explicar && (
        <span className="recibo" aria-label="Aporte de cada señal">
          {SENALES.map((s, i) => (
            <span key={s.clave} className={i === fuerte && partes[i] > 0 ? 'fuerte' : ''} title={`${s.nombre}: ${Math.round(partes[i] * 100)} %`}>
              <b className="num">{partes[i] > 0 ? `${Math.round(partes[i] * 100)} %` : '—'}</b>
              <i style={{ transform: `scaleX(${partes[i]})` }} />
            </span>
          ))}
        </span>
      )}
    </li>
  );
}

function RecsCargando() {
  return (
    <ol className="recs" aria-hidden="true">
      {Array.from({ length: 5 }, (_, i) => (
        <li className="rec" key={i}>
          <span /><span className="rec-foto esqueleto" style={{ border: 0 }} />
          <span className="rec-texto"><span className="esqueleto" style={{ height: 14, width: '70%' }} /><span className="esqueleto" style={{ height: 12, width: 140 }} /></span>
          <span className="esqueleto" style={{ height: 16, width: 64, justifySelf: 'end' }} />
        </li>
      ))}
    </ol>
  );
}
