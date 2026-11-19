import { useState } from 'react';
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

  function elegir(lista) {
    const pdf = lista?.[0];
    if (!pdf || fase === 'subiendo') return;
    setArchivo(null);
    if (!pdf.name.toLowerCase().endsWith('.pdf')) { setError(new Error('Elige un archivo PDF.')); setFase('error'); return; }
    if (pdf.size > MAX_MB * 1024 * 1024) { setError(new Error(`El PDF pasa de ${MAX_MB} MB.`)); setFase('error'); return; }
    setArchivo(pdf);
    setFase('elegir');
    setError(null);
    if (!titulo) setTitulo(pdf.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' '));
  }

  async function indexar(evento) {
    evento.preventDefault();
    if (!archivo || !titulo.trim() || fase === 'subiendo' || fase === 'listo') return;
    const formulario = new FormData();
    formulario.append('archivo', archivo);
    formulario.append('titulo', titulo.trim());
    formulario.append('autores', autores.trim());
    formulario.append('anio', anio);
    formulario.append('tipo', tipo);
    setError(null);
    setFase('subiendo');
    try {
      const documento = await api.subir(formulario);
      setResultado({ ...documento, titulo: titulo.trim() });
      setFase('listo');
      alSubir();
    } catch (e) {
      setError(e);
      setFase('error');
    }
  }

  function reiniciar() {
    setArchivo(null);
    setTitulo('');
    setAutores('');
    setAnio(String(new Date().getFullYear()));
    setTipo('paper');
    setResultado(null);
    setFase('elegir');
  }

  const hecho = fase === 'listo' && resultado;
  const bloqueado = fase === 'subiendo' || fase === 'listo';

  return (
    <div className="pagina">
      <div className="titulo-texto">
        <h1>Subir PDF</h1>
        <span className="sub">Agrega un paper o una clase para consultarlos desde el asistente.</span>
      </div>

      <div className="columnas">
        <form className="principal" onSubmit={indexar}>
          <label className="zona" data-encima={encima} data-bloqueado={bloqueado}
                 onDragOver={(e) => { e.preventDefault(); setEncima(true); }} onDragLeave={() => setEncima(false)}
                 onDrop={(e) => { e.preventDefault(); setEncima(false); elegir(e.dataTransfer.files); }}>
            <IconoSubir />
            <span style={{ fontWeight: 500 }}>{archivo ? archivo.name : 'Arrastra un PDF o haz clic para elegirlo'}</span>
            <span className="sub num" style={{ fontSize: 12 }}>
              {archivo ? `${(archivo.size / 1024 / 1024).toFixed(1)} MB` : `Un paper o una clase · hasta ${MAX_MB} MB`}
            </span>
            <input key={resultado?.id ?? 'nuevo'} type="file" disabled={bloqueado} accept="application/pdf" className="oculto" onChange={(e) => elegir(e.target.files)} />
          </label>

          <fieldset className="panel formulario" disabled={bloqueado} aria-labelledby="datos-pdf">
            <h2 id="datos-pdf">Datos del documento</h2>
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
              <button className="btn" type="submit" disabled={!archivo || !titulo.trim() || bloqueado}>
                {fase === 'subiendo' ? 'Indexando…' : 'Indexar documento'}
              </button>
            </div>
          </fieldset>
        </form>

        <section className="panel lateral resumen-pdf" aria-label="Estado del documento" aria-live="polite">
          {fase === 'elegir' && <>
            <h2>Qué pasa con tu PDF</h2>
            <p className="sub">El asistente extrae el texto, lo divide en fragmentos y los añade al índice de búsqueda con BM25.</p>
          </>}
          {fase === 'subiendo' && <>
            <h2>Procesando el documento</h2>
            <p className="sub">La extracción y la indexación pueden tardar. Te avisaremos cuando el documento esté disponible.</p>
          </>}
          {fase === 'error' && (
            <div className="error-bloque" role="alert"><IconoError /><span>{error?.message}</span></div>
          )}
          {hecho && <>
            <h2>Documento listo para consultar</h2>
            <p className="sub">{resultado.titulo}</p>
            <dl className="metricas-pdf">
              <div><dt>Páginas procesadas</dt><dd>{entero(resultado.paginas)}</dd></div>
              <div><dt>Fragmentos indexados</dt><dd>{entero(resultado.fragmentos)}</dd></div>
            </dl>
            <div className="acciones">
              <button className="btn" onClick={() => preguntarSobre(`¿De qué trata «${resultado.titulo}»?`)}>Preguntar</button>
              <a className="btn2" href={enlace.documento(resultado.id)}>Ver fragmentos</a>
            </div>
            <button type="button" className="texto-btn" onClick={reiniciar}>Subir otro PDF</button>
          </>}
        </section>
      </div>
    </div>
  );
}
