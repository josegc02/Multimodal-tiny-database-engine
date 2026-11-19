import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
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

export default function Preguntar({ reciente, auto, borrador, limpiarBorrador, alResponder }) {
  const [texto, setTexto] = useState(borrador || '');
  const [fase, setFase] = useState(reciente ? 'listo' : 'inicio'); // inicio | cargando | listo | error
  const [datos, setDatos] = useState(reciente?.datos ?? null);
  const [error, setError] = useState(null);
  const [pregunta, setPregunta] = useState(reciente?.pregunta ?? '');
  const [cita, setCita] = useState(null);
  const [origenCita, setOrigenCita] = useState(null);
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
    setDatos(null);
    setFase('cargando');
    setError(null);
    try {
      const respuesta = await api.preguntar({ pregunta: limpia, usarLlm });
      setDatos(respuesta);
      setCita(null);
      setOrigenCita(null);
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
    if (evento.key === 'Enter' && !evento.shiftKey && !evento.nativeEvent.isComposing) { evento.preventDefault(); enviar(texto); }
  };
  const elegirCita = (n, origen) => {
    setCita(n);
    setOrigenCita(origen ? { numero: n, elemento: origen } : null);
    const fuente = document.getElementById(`fuente-${n}`);
    if (!fuente) return;
    fuente.focus({ preventScroll: true });
    fuente.scrollIntoView({ block: 'nearest' });
  };

  const volverACita = () => {
    origenCita.elemento.focus({ preventScroll: true });
    origenCita.elemento.scrollIntoView({ block: 'center' });
  };

  const fragmentos = datos?.fragmentos ?? [];
  const documentos = new Set(fragmentos.map((f) => f.paper_id)).size;
  const inicio = fase === 'inicio';
  const conFuentes = fase === 'listo' && fragmentos.length > 0;
  let subtitulo = 'Consulta las clases y los papers de Bases de Datos II.';
  if (fase === 'cargando') subtitulo = `Buscando en la biblioteca… ${segundos} s`;
  if (fase === 'listo') {
    subtitulo = conFuentes
      ? `${fragmentos.length} ${fragmentos.length === 1 ? 'fragmento' : 'fragmentos'} de ${documentos} ${documentos === 1 ? 'documento' : 'documentos'}`
      : 'No se encontraron fuentes';
  }
  if (fase === 'error') subtitulo = 'No se pudo completar la consulta';

  return (
    <div className={`pagina ${inicio ? 'consulta-inicio' : 'consulta'}`}>
      <header className="titulo-fila">
        <div className="titulo-texto">
          <h1>{inicio ? 'Investiga con tus fuentes' : pregunta}</h1>
          <p className="sub" aria-live="polite">{subtitulo}</p>
        </div>
        {!inicio && fase !== 'cargando' && <a className="btn2" href={enlace.preguntar} onClick={() => {
          setFase('inicio');
          setDatos(null);
          setTexto('');
        }}>Nueva pregunta</a>}
      </header>

      <div className={`consulta-rejilla${conFuentes ? ' con-fuentes' : ''}`}>
        {!inicio && <div className="consulta-respuesta">
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
                      La generación de respuestas está desactivada para esta consulta. Puedes leer los fragmentos recuperados en Fuentes.
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
            </>
          )}

        </div>}
        {conFuentes && <Fuentes datos={datos} cita={cita} elegir={elegirCita}
                              numeroParaVolver={origenCita?.numero} volverACita={volverACita} />}
        {fase === 'listo' && datos?.traza && <Traza datos={datos} />}

        <form className="panel redactor" onSubmit={alEnviar}>
            <label htmlFor="pregunta" className="oculto">Tu pregunta</label>
            <textarea id="pregunta" ref={campo} rows={2} value={texto} onChange={(e) => setTexto(e.target.value)}
                      onKeyDown={alTeclear} maxLength={1000}
                      placeholder="Pregunta sobre los papers o las clases del curso" />
            <button className="btn" type="submit" disabled={fase === 'cargando' || !texto.trim()}>Preguntar</button>
        </form>
        {inicio && (
          <section className="ejemplos" aria-labelledby="titulo-ejemplos">
            <h2 id="titulo-ejemplos">Preguntas para empezar</h2>
            <div className="ejemplos-lista">
              {SUGERENCIAS.map((s) => (
                <button key={s} className="ejemplo" onClick={() => enviar(s)}>
                  {s}<span aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function ErrorRespuesta({ error, reintentar, soloFragmentos }) {
  const delLlm = error?.estado === 502;
  const sinClave = delLlm && /API key|credencial/i.test(error?.message ?? '');
  return (
    <section className="panel respuesta" aria-label="Error" role="alert">
      <div className="error-bloque">
        <IconoError />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="error-titulo">{sinClave ? 'Revisa la clave del modelo' : delLlm ? 'El modelo no está disponible' : 'No se pudo responder'}</span>
          <span style={{ color: 'var(--tinta-2)' }}>{sinClave ? 'La clave falta o el proveedor la rechazó. Puedes continuar con los fragmentos de la biblioteca.' : error?.message}</span>
        </div>
      </div>
      <div className="acciones" style={{ paddingLeft: 26 }}>
        {delLlm && <button className="btn" onClick={soloFragmentos}>Buscar solo fragmentos</button>}
        {error?.estado !== 422 && <button className={delLlm ? 'btn2' : 'btn'} onClick={reintentar}>Reintentar</button>}
      </div>
    </section>
  );
}
