import { useState } from 'react';
import { api } from '../api.js';
import { esClase, paginas, referencia, sinCorreos } from '../formato.js';

const CORTE = 320; // caracteres del fragmento que se ven antes de "Ver completo"

export default function Fuentes({ fase, datos, cita, elegir }) {
  const terminos = (datos?.consulta ?? '').split(/\s+/).filter((t) => t.length > 2);
  const fragmentos = datos?.fragmentos ?? [];
  const citadas = new Set(datos?.citas ?? []);
  const maximo = Math.max(...fragmentos.map((f) => f.puntaje), 1);

  return (
    <aside className="lateral" aria-label="Fuentes">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', padding: '0 2px' }}>
        <h2>Fuentes</h2>
        {fase === 'listo' && fragmentos.length > 0 && <span className="sub num" style={{ fontSize: 12 }}>{fragmentos.length} · ordenadas por BM25</span>}
      </div>

      {fase === 'cargando' && [1, 2, 3].map((n) => (
        <div key={n} className="panel" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="esqueleto" style={{ height: 12, width: '60%' }} />
          <div className="esqueleto" style={{ height: 14, width: '90%' }} />
          <div className="esqueleto" style={{ height: 12, width: '75%' }} />
        </div>
      ))}
      {(fase === 'inicio' || fase === 'error') && (
        <div className="aviso">Las fuentes aparecen al responder: cada fragmento con su documento, su página y su puntaje BM25.</div>
      )}
      {fase === 'listo' && fragmentos.length === 0 && (
        <div className="aviso">BM25 no encontró fragmentos con estas palabras clave: {datos?.consulta || '—'}.</div>
      )}
      {fase === 'listo' && fragmentos.map((f) => (
        <Fuente key={f.id} f={f} activa={f.n === cita} citada={citadas.has(f.n)} terminos={terminos}
                sinLlm={datos.modo === 'sin_llm'} ancho={(f.puntaje / maximo) * 100} elegir={elegir} />
      ))}
    </aside>
  );
}

function Fuente({ f, activa, citada, sinLlm, ancho, elegir, terminos }) {
  const [completo, setCompleto] = useState(false);
  const clase = esClase(f);
  const texto = sinCorreos(f.texto);
  const corto = texto.length > CORTE && !completo ? `${texto.slice(0, CORTE).replace(/\s+\S*$/, '')}…` : texto;
  let uso = citada ? 'Citada en la respuesta' : 'Recuperada, no citada';
  if (sinLlm) uso = clase ? 'Clase del curso' : 'Paper';

  return (
    <article id={`fuente-${f.n}`} className="fuente" data-activa={activa}>
      <button className="fuente-cabeza" onClick={() => elegir(f.n)} aria-label={`Resaltar la fuente ${f.n}`}>
        <span className="cita" aria-pressed={activa}>{f.n}</span>
        <span className="fuente-lugar">{referencia(f)} · {clase ? '' : `${f.anio} · `}{paginas(f, clase)}</span>
        <span className="fuente-puntaje num">BM25 {f.puntaje.toFixed(2)}</span>
      </button>
      <div className="pista"><div style={{ width: `${Math.round(ancho)}%` }} /></div>
      <span className="fuente-titulo">{f.titulo}</span>
      <p className="fuente-texto">“{resaltar(corto, terminos)}”</p>
      <div className="fuente-pie">
        <span className="sub">{uso}</span>
        <span className="enlaces">
          {texto.length > CORTE && (
            <button className="texto-btn" style={{ fontSize: 12 }} onClick={() => setCompleto(!completo)}>
              {completo ? 'Ver menos' : 'Ver completo'}
            </button>
          )}
          <a href={api.urlPdf(f.paper_id, f.pagina)} target="_blank" rel="noreferrer">
            {clase ? `Abrir en la diap. ${f.pagina}` : `PDF, p. ${f.pagina}`}
          </a>
          {f.url && <a href={f.url} target="_blank" rel="noreferrer">arXiv</a>}
        </span>
      </div>
    </article>
  );
}

// Marca en el fragmento las palabras clave de la consulta (y sus variantes: index, indexing).
function resaltar(texto, terminos) {
  if (!terminos.length) return texto;
  const raices = terminos.map((t) => t.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, Math.max(4, t.length - 2))).filter(Boolean);
  if (!raices.length) return texto;
  const patron = new RegExp(`\\b(${raices.join('|')})[a-z0-9-]*`, 'gi');
  const partes = [];
  let ultimo = 0;
  for (const m of texto.matchAll(patron)) {
    if (m.index > ultimo) partes.push(texto.slice(ultimo, m.index));
    partes.push(<mark key={m.index}>{m[0]}</mark>);
    ultimo = m.index + m[0].length;
  }
  partes.push(texto.slice(ultimo));
  return partes;
}
