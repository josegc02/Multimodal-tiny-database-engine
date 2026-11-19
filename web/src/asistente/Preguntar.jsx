import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { entero } from '../formato.js';
import { IconoError } from '../Iconos.jsx';
import { enlace, ir } from '../ruta.js';
import Fuentes from './Fuentes.jsx';
import Respuesta from './Respuesta.jsx';
import Traza from './Traza.jsx';

// Preguntas que el corpus responde bien (benchmarks/asistente/preguntas.json).
const SUGERENCIAS = [
  '¿Cómo se construye un índice invertido con SPIMI?',
  '¿Cómo funciona la búsqueda de vecinos cercanos en HNSW?',
  '¿Qué hace el buffer manager de un SGBD?',
  '¿Qué es la fragmentación horizontal en bases de datos distribuidas?',
];

export default function Preguntar({ reciente, auto, estado, borrador, limpiarBorrador, alResponder }) {
  const [texto, setTexto] = useState(borrador || '');
  const [fase, setFase] = useState(reciente ? 'listo' : 'inicio'); // inicio | cargando | listo | error
  const [datos, setDatos] = useState(reciente?.datos ?? null);
  const [error, setError] = useState(null);
  const [pregunta, setPregunta] = useState(reciente?.pregunta ?? '');
  const [cita, setCita] = useState(1);
  const [segundos, setSegundos] = useState(0);
  const campo = useRef(null);
  const autoEnviada = useRef(false); // StrictMode monta dos veces en desarrollo: una sola petición

  useEffect(() => { if (borrador) { limpiarBorrador(); campo.current?.focus(); } }, [borrador, limpiarBorrador]);
  useEffect(() => {
    if (fase !== 'cargando') return undefined;
    setSegundos(0);
    const reloj = setInterval(() => setSegundos((s) => s + 1), 1000);
    return () => clearInterval(reloj);
  }, [fase]);

  useEffect(() => {
    if (auto && !autoEnviada.current) { autoEnviada.current = true; enviar(auto); }
  }, [auto]); // eslint-disable-line react-hooks/exhaustive-deps

  async function enviar(textoPregunta, { usarLlm = true } = {}) {
    const limpia = textoPregunta.trim();
    if (!limpia || fase === 'cargando') return;
    setPregunta(limpia);
    setFase('cargando');
    setError(null);
    try {
      const respuesta = await api.preguntar({ pregunta: limpia, usarLlm });
      setDatos(respuesta);
      setCita(1);
      setFase('listo');
      setTexto('');
      ir(enlace.reciente(alResponder(respuesta)));
    } catch (e) {
      setError(e);
      setFase('error');
    }
  }

  const alEnviar = (evento) => { evento.preventDefault(); enviar(texto); };
  const alTeclear = (evento) => {
    if (evento.key === 'Enter' && !evento.shiftKey) { evento.preventDefault(); enviar(texto); }
  };
  const elegirCita = (n) => {
    setCita(n);
    document.getElementById(`fuente-${n}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };

  const fragmentos = datos?.fragmentos ?? [];
  const documentos = new Set(fragmentos.map((f) => f.paper_id)).size;
  let subtitulo = estado?.corpus
    ? `Respuestas con los ${entero(estado.documentos)} papers y clases cargados, citando cada fuente.`
    : 'Respuestas con los papers y clases del curso, citando cada fuente.';
  if (fase === 'cargando') subtitulo = `Buscando en ${estado?.corpus ? entero(estado.fragmentos) : 'los'} fragmentos y redactando · ${segundos} s`;
  if (fase === 'listo' && datos) {
    subtitulo = fragmentos.length
      ? `${fragmentos.length} fuente${fragmentos.length === 1 ? '' : 's'} de ${documentos} documento${documentos === 1 ? '' : 's'} · ${datos.traza ? `${datos.traza.s_total.toFixed(1)} s` : ''}`
      : 'Sin fragmentos relacionados en el corpus';
  }
  if (fase === 'error') subtitulo = 'No se pudo responder';

  return (
    <div className="pagina">
      <div className="titulo-fila">
        <div className="titulo-texto">
          <h1>{fase === 'inicio' ? 'Pregunta sobre el curso' : pregunta}</h1>
          <span className="sub num" aria-live="polite">{subtitulo}</span>
        </div>
        {fase !== 'inicio' && <a className="btn2" href={enlace.preguntar} onClick={() => { setFase('inicio'); setDatos(null); }}>Nueva pregunta</a>}
      </div>

      <div className="columnas">
        <div className="principal">
          {fase === 'inicio' && (
            <section className="panel respuesta" aria-label="Sugerencias">
              <p style={{ fontSize: 15, color: 'var(--tinta-2)' }}>
                Busca en los papers de arXiv y en las clases del curso con BM25, y responde citando cada fragmento.
                Prueba con una de estas:
              </p>
              <div className="sugerencias">
                {SUGERENCIAS.map((s) => <button key={s} className="sugerencia" onClick={() => enviar(s)}>{s}</button>)}
              </div>
            </section>
          )}

          {fase === 'cargando' && (
            <section className="panel respuesta" aria-label="Cargando la respuesta" aria-busy="true">
              {[96, 92, 98, 64].map((ancho) => <div key={ancho} className="esqueleto" style={{ width: `${ancho}%` }} />)}
            </section>
          )}

          {fase === 'error' && <ErrorRespuesta error={error} reintentar={() => enviar(pregunta)}
                                              soloFragmentos={() => enviar(pregunta, { usarLlm: false })} />}

          {fase === 'listo' && datos && (
            <>
              {datos.respuesta && fragmentos.length > 0 && <Respuesta datos={datos} cita={cita} elegir={elegirCita} />}
              {(!datos.respuesta || !fragmentos.length) && (
                <section className="panel respuesta" aria-label="Respuesta">
                  {datos.modo === 'sin_llm' && fragmentos.length > 0 && (
                    <p style={{ fontSize: 15, color: 'var(--tinta-2)' }}>
                      Sin LLM: a la derecha están los {fragmentos.length} fragmentos que encontró BM25, sin redactar una respuesta.
                    </p>
                  )}
                  {!fragmentos.length && (
                    <>
                      <p>No encontré fragmentos de los papers ni de las clases sobre esto.</p>
                      <p style={{ fontSize: 14, color: 'var(--tinta-2)' }}>
                        El asistente solo responde con los documentos cargados: papers de bases de datos y recuperación de
                        información, y las clases del curso. Puedes subir un PDF para ampliarlo, o probar con:
                      </p>
                      <div className="sugerencias">
                        {SUGERENCIAS.slice(0, 3).map((s) => <button key={s} className="sugerencia" onClick={() => enviar(s)}>{s}</button>)}
                      </div>
                    </>
                  )}
                </section>
              )}
              {datos.traza && <Traza datos={datos} />}
            </>
          )}

          <form className="panel redactor" onSubmit={alEnviar}>
            <label htmlFor="pregunta" className="oculto">Tu pregunta</label>
            <textarea id="pregunta" ref={campo} rows={2} value={texto} onChange={(e) => setTexto(e.target.value)}
                      onKeyDown={alTeclear} maxLength={1000}
                      placeholder="Pregunta sobre los papers o las clases del curso" />
            <button className="btn" type="submit" disabled={fase === 'cargando' || !texto.trim()}>Preguntar</button>
          </form>
        </div>

        <Fuentes fase={fase} datos={datos} cita={cita} elegir={elegirCita} />
      </div>
    </div>
  );
}

function ErrorRespuesta({ error, reintentar, soloFragmentos }) {
  const delLlm = error?.estado === 502;
  return (
    <section className="panel respuesta" aria-label="Error" role="alert">
      <div className="error-bloque">
        <IconoError />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="error-titulo">{delLlm ? 'El LLM no respondió' : 'No se pudo responder'}</span>
          <span style={{ color: 'var(--tinta-2)' }}>{error?.message}</span>
        </div>
      </div>
      <div className="acciones" style={{ paddingLeft: 26 }}>
        {delLlm && <button className="btn" onClick={soloFragmentos}>Responder solo con fragmentos</button>}
        {error?.estado !== 422 && <button className={delLlm ? 'btn2' : 'btn'} onClick={reintentar}>Reintentar</button>}
      </div>
    </section>
  );
}
