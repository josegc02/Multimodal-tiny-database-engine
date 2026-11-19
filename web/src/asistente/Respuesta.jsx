import { useState } from 'react';
import { esClase, paginas, partirRespuesta, referencia, sinCorreos } from '../formato.js';

// La respuesta del LLM: cabecera con el modelo, párrafos con citas que muestran su
// fuente al pasar el mouse, y al pie los documentos en que se basa.
export default function Respuesta({ datos, cita, elegir }) {
  const [vista, setVista] = useState(null); // cita con la vista previa abierta
  const [copiado, setCopiado] = useState(false);
  const fragmentos = datos.fragmentos ?? [];
  const porNumero = Object.fromEntries(fragmentos.map((f) => [f.n, f]));
  const parrafos = partirRespuesta(datos.respuesta);
  const traza = datos.traza ?? {};

  // Documentos citados, en el orden de su primera cita, con sus números.
  const documentos = [];
  for (const n of datos.citas ?? []) {
    const f = porNumero[n];
    if (!f) continue;
    let doc = documentos.find((d) => d.paper_id === f.paper_id);
    if (!doc) { doc = { paper_id: f.paper_id, f, numeros: [] }; documentos.push(doc); }
    doc.numeros.push(n);
  }
  const sinCitar = fragmentos.length - (datos.citas ?? []).length;

  async function copiar() {
    const fuentes = fragmentos.map((f) => `[${f.n}] ${f.titulo}, ${paginas(f, esClase(f))}`).join('\n');
    try {
      await navigator.clipboard.writeText(`${datos.respuesta}\n\nFuentes:\n${fuentes}`);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      setCopiado(false);
    }
  }

  return (
    <section className="panel respuesta" aria-label="Respuesta">
      <div className="respuesta-cabeza">
        <h2>Respuesta</h2>
        <span className="sub num" style={{ fontSize: 12 }}>
          {traza.modelo ? `${traza.modelo} · ${traza.s_redaccion?.toFixed(1)} s` : ''}
        </span>
        <button className="texto-btn" style={{ marginLeft: 'auto', fontSize: 13 }} onClick={copiar}>
          {copiado ? 'Copiada' : 'Copiar con fuentes'}
        </button>
      </div>

      <div className="respuesta-cuerpo">
        {parrafos.map((parrafo, i) => (
          <p key={i}>
            {parrafo.map((trozo, j) => {
              if (!trozo.cita) return <span key={j}>{enfasis(trozo.texto)}</span>;
              const f = porNumero[trozo.cita];
              return (
                <span key={j} className="cita-ancla"
                      onMouseEnter={() => setVista(`${i}-${j}`)} onMouseLeave={() => setVista(null)}>
                  <button className="cita" aria-pressed={trozo.cita === cita} aria-describedby={f ? `previa-${i}-${j}` : undefined}
                          onFocus={() => setVista(`${i}-${j}`)} onBlur={() => setVista(null)}
                          onClick={() => elegir(trozo.cita)}>{trozo.cita}</button>
                  {f && vista === `${i}-${j}` && (
                    <span role="tooltip" id={`previa-${i}-${j}`} className="previa">
                      <span className="previa-lugar">{referencia(f)} · {paginas(f, esClase(f))}</span>
                      <span className="previa-titulo">{f.titulo}</span>
                      <span className="previa-texto">“{recortar(sinCorreos(f.texto), 180)}”</span>
                    </span>
                  )}
                </span>
              );
            })}
          </p>
        ))}
      </div>

      {documentos.length > 0 && (
        <div className="basada">
          <span className="sub" style={{ fontSize: 12 }}>Basada en</span>
          <div className="basada-lista">
            {documentos.map((d) => (
              <button key={d.paper_id} className="documento-chip" onClick={() => elegir(d.numeros[0])}>
                <span className="tipo">{esClase(d.f) ? 'Clase' : 'Paper'}</span>
                <span className="nombre">{esClase(d.f) ? d.f.titulo : `${referencia(d.f)} · ${d.f.anio}`}</span>
                <span className="numeros num">{[...new Set(d.numeros)].map((n) => `[${n}]`).join(' ')}</span>
              </button>
            ))}
          </div>
          {sinCitar > 0 && <span className="sub" style={{ fontSize: 12 }}>{sinCitar} fuente{sinCitar === 1 ? '' : 's'} recuperada{sinCitar === 1 ? '' : 's'} sin citar</span>}
        </div>
      )}
    </section>
  );
}

// El LLM a veces marca términos con markdown: **negrita** y *cursiva*.
function enfasis(texto) {
  return texto.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g).map((parte, i) => {
    if (/^\*\*[^*]+\*\*$/.test(parte)) return <strong key={i} style={{ fontWeight: 500 }}>{parte.slice(2, -2)}</strong>;
    if (/^\*[^*]+\*$/.test(parte)) return <em key={i}>{parte.slice(1, -1)}</em>;
    return parte;
  });
}

const recortar = (texto, n) => (texto.length > n ? `${texto.slice(0, n).replace(/\s+\S*$/, '')}…` : texto);
