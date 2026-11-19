import { useRef, useState } from 'react';
import { api } from '../api.js';
import { entero } from '../formato.js';
import { IconoError, IconoSubir } from '../Iconos.jsx';
import { enlace } from '../ruta.js';

const MAX_MB = 20;

export default function Subir({ alSubir, preguntarSobre }) {
  const [archivo, setArchivo] = useState(null);
  const [titulo, setTitulo] = useState('');
  const [autores, setAutores] = useState('');
  const [anio, setAnio] = useState(String(new Date().getFullYear()));
  const [tipo, setTipo] = useState('paper');
  const [fase, setFase] = useState('elegir'); // elegir | subiendo | listo | error
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState(null);
  const [encima, setEncima] = useState(false);
  const entrada = useRef(null);

  function elegir(lista) {
    const pdf = lista?.[0];
    if (!pdf) return;
    if (!pdf.name.toLowerCase().endsWith('.pdf')) { setError(new Error('Elige un archivo PDF.')); setFase('error'); return; }
    if (pdf.size > MAX_MB * 1024 * 1024) { setError(new Error(`El PDF pasa de ${MAX_MB} MB.`)); setFase('error'); return; }
    setArchivo(pdf);
    setFase('elegir');
    setError(null);
    if (!titulo) setTitulo(pdf.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' '));
  }

  async function indexar(evento) {
    evento.preventDefault();
    if (!archivo || !titulo.trim()) return;
    const formulario = new FormData();
    formulario.append('archivo', archivo);
    formulario.append('titulo', titulo.trim());
    formulario.append('autores', autores.trim());
    formulario.append('anio', anio);
    formulario.append('tipo', tipo);
    setFase('subiendo');
    try {
      setResultado(await api.subir(formulario));
      setFase('listo');
      alSubir();
    } catch (e) {
      setError(e);
      setFase('error');
    }
  }

  const hecho = fase === 'listo' && resultado;
  const pasos = [
    ['Texto extraído', 'Por página, con pypdf', hecho ? `${entero(resultado.paginas)} páginas · ${resultado.ms_extraccion.toFixed(0)} ms` : '—'],
    ['Fragmentado', '200–500 palabras, sin bibliografía', hecho ? `${entero(resultado.fragmentos)} fragmentos · ${entero(resultado.palabras)} palabras` : '—'],
    ['Insertado e indexado', 'INSERT en papers y fragmentos; el índice SPIMI se actualiza con él', hecho ? `1 + ${entero(resultado.fragmentos)} filas · ${resultado.ms_insercion.toFixed(0)} ms` : '—'],
  ];

  return (
    <div className="pagina">
      <div className="titulo-texto">
        <h1>Subir PDF</h1>
        <span className="sub">El texto se extrae por página, se corta en fragmentos de 200–500 palabras y entra al índice SPIMI de fragmentos.texto.</span>
      </div>

      <div className="columnas">
        <form className="principal" onSubmit={indexar}>
          <label className="zona" data-encima={encima}
                 onDragOver={(e) => { e.preventDefault(); setEncima(true); }} onDragLeave={() => setEncima(false)}
                 onDrop={(e) => { e.preventDefault(); setEncima(false); elegir(e.dataTransfer.files); }}>
            <IconoSubir />
            <span style={{ fontWeight: 500 }}>{archivo ? archivo.name : 'Arrastra un PDF o haz clic para elegirlo'}</span>
            <span className="sub num" style={{ fontSize: 12 }}>
              {archivo ? `${(archivo.size / 1024 / 1024).toFixed(1)} MB` : `Un paper o una clase · hasta ${MAX_MB} MB`}
            </span>
            <input ref={entrada} type="file" accept="application/pdf" className="oculto" onChange={(e) => elegir(e.target.files)} />
          </label>

          <section className="panel formulario" aria-label="Datos del documento">
            <h2>Datos del documento</h2>
            <div className="segmentos" role="group" aria-label="Tipo de documento" style={{ alignSelf: 'flex-start' }}>
              <button type="button" aria-pressed={tipo === 'paper'} onClick={() => setTipo('paper')}>Paper</button>
              <button type="button" aria-pressed={tipo === 'clase'} onClick={() => setTipo('clase')}>Clase del curso</button>
            </div>
            <label className="campo">Título
              <input value={titulo} onChange={(e) => setTitulo(e.target.value)} required maxLength={300} />
            </label>
            <div className="rejilla-2">
              <label className="campo">Autores
                <input value={autores} onChange={(e) => setAutores(e.target.value)} maxLength={300} />
              </label>
              <label className="campo">Año
                <input className="num" value={anio} onChange={(e) => setAnio(e.target.value.replace(/\D/g, '').slice(0, 4))} inputMode="numeric" required />
              </label>
            </div>
            <div className="acciones" style={{ justifyContent: 'flex-end' }}>
              <button className="btn" type="submit" disabled={!archivo || !titulo.trim() || fase === 'subiendo'}>
                {fase === 'subiendo' ? 'Indexando…' : 'Indexar documento'}
              </button>
            </div>
          </section>
        </form>

        <section className="panel lateral" aria-label="Avance" aria-live="polite" style={{ padding: '16px 20px 20px' }}>
          <h2>Avance</h2>
          {fase === 'subiendo' && <p className="sub">Extrayendo el texto y fragmentando {archivo?.name}…</p>}
          {fase === 'error' && (
            <div className="error-bloque" role="alert"><IconoError /><span>{error?.message}</span></div>
          )}
          {pasos.map(([nombre, detalle, valor]) => (
                <div key={nombre} className="paso">
                  <svg width="16" height="16" viewBox="0 0 16 16" style={{ marginTop: 2 }} aria-hidden="true">
                    <circle cx="8" cy="8" r="6.5" fill={hecho ? '#141414' : '#fff'} stroke={hecho ? '#141414' : '#c4c8cf'} strokeWidth="1.5" />
                  </svg>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontWeight: 500 }}>{nombre}</span>
                    <span className="sub" style={{ fontSize: 12, lineHeight: '16px' }}>{detalle}</span>
                  </div>
                  <span className="num" style={{ fontSize: 12, color: 'var(--tinta-2)', textAlign: 'right' }}>{valor}</span>
                </div>
          ))}
          {hecho && (
            <>
              <div className="acciones">
                <button className="btn" onClick={() => preguntarSobre(`¿De qué trata «${titulo.trim()}»?`)}>Preguntar sobre este documento</button>
                <a className="btn2" href={enlace.documento(resultado.id)}>Ver sus fragmentos</a>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
