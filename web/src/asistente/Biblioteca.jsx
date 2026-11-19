import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { autoresCortos, entero, esClase, TEMAS } from '../formato.js';
import { IconoBuscar, IconoError } from '../Iconos.jsx';
import { enlace } from '../ruta.js';

const PASO = 50; // filas por tanda

export default function Biblioteca() {
  const [documentos, setDocumentos] = useState(null);
  const [error, setError] = useState(null);
  const [busqueda, setBusqueda] = useState('');
  const [tipo, setTipo] = useState('todos');
  const [tema, setTema] = useState('');
  const [visibles, setVisibles] = useState(PASO);

  const cargar = () => { setError(null); api.documentos().then(setDocumentos).catch(setError); };
  useEffect(cargar, []);
  useEffect(() => setVisibles(PASO), [busqueda, tipo, tema]);

  const totales = useMemo(() => {
    const lista = documentos ?? [];
    return { todos: lista.length, papers: lista.filter((d) => !esClase(d)).length, clases: lista.filter(esClase).length };
  }, [documentos]);
  const temas = useMemo(() => [...new Set((documentos ?? []).map((d) => d.tema))].sort(
    (a, b) => (TEMAS[a] ?? a).localeCompare(TEMAS[b] ?? b)), [documentos]);
  const filas = useMemo(() => {
    const texto = busqueda.trim().toLowerCase();
    return (documentos ?? [])
      .filter((d) => tipo === 'todos' || (tipo === 'clases' ? esClase(d) : !esClase(d)))
      .filter((d) => !tema || d.tema === tema)
      .filter((d) => !texto || `${d.titulo} ${d.autores}`.toLowerCase().includes(texto));
  }, [documentos, busqueda, tipo, tema]);
  const fragmentos = (documentos ?? []).reduce((suma, d) => suma + d.fragmentos, 0);

  return (
    <div className="pagina">
      <div className="titulo-texto">
        <h1>Biblioteca</h1>
        <span className="sub num">
          {documentos ? `${entero(totales.papers)} papers y ${entero(totales.clases)} clases del curso · ${entero(fragmentos)} fragmentos indexados con SPIMI` : 'Cargando la biblioteca…'}
        </span>
      </div>

      <div className="herramientas">
        <label className="buscador">
          <IconoBuscar />
          <span className="oculto">Buscar por título o autor</span>
          <input value={busqueda} onChange={(e) => setBusqueda(e.target.value)} placeholder="Título o autor" />
        </label>
        <div className="segmentos" role="group" aria-label="Tipo de documento">
          {[['todos', 'Todos'], ['papers', 'Papers'], ['clases', 'Clases']].map(([id, texto]) => (
            <button key={id} aria-pressed={tipo === id} onClick={() => setTipo(id)}>
              {texto} <span className="num sub">{documentos ? totales[id] : ''}</span>
            </button>
          ))}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--gris)' }}>
          Tema
          <select className="selector" value={tema} onChange={(e) => setTema(e.target.value)}>
            <option value="">Todos</option>
            {temas.map((t) => <option key={t} value={t}>{TEMAS[t] ?? t}</option>)}
          </select>
        </label>
      </div>

      <div className="panel">
        {error && (
          <div className="respuesta" role="alert">
            <div className="error-bloque"><IconoError /><span>{error.message}</span></div>
            <div className="acciones"><button className="btn2" onClick={cargar}>Reintentar</button></div>
          </div>
        )}
        {!error && (
          <div className="tabla-marco">
            <table style={{ minWidth: 720 }}>
              <thead>
                <tr>
                  <th style={{ width: '52%' }}>Título</th>
                  <th>Tipo</th>
                  <th>Tema</th>
                  <th className="num">Año</th>
                  <th className="num">Fragmentos</th>
                </tr>
              </thead>
              <tbody>
                {!documentos && [1, 2, 3, 4, 5].map((n) => (
                  <tr key={n}><td colSpan={5}><div className="esqueleto" style={{ width: `${60 + n * 6}%` }} /></td></tr>
                ))}
                {documentos && filas.length === 0 && (
                  <tr><td colSpan={5} className="sub">Ningún documento coincide con estos filtros.</td></tr>
                )}
                {filas.slice(0, visibles).map((d) => (
                  <tr key={d.id}>
                    <td>
                      <a href={enlace.documento(d.id)} style={{ color: 'var(--tinta)', fontWeight: 500 }}>{d.titulo}</a>
                      <span className="celda-sub">{autoresCortos(d.autores)}</span>
                    </td>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--tinta-2)' }}>{esClase(d) ? 'Clase' : 'Paper'}</td>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--tinta-2)' }}>{TEMAS[d.tema] ?? d.tema}</td>
                    <td className="num">{d.anio}</td>
                    <td className="num">{entero(d.fragmentos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {documentos && (
              <div className="pie-tabla num">
                <span>{filas.length ? `1–${Math.min(visibles, filas.length)} de ${entero(filas.length)} documentos` : ''}</span>
                {visibles < filas.length && <button className="texto-btn" style={{ fontSize: 12 }} onClick={() => setVisibles(visibles + PASO)}>Cargar {Math.min(PASO, filas.length - visibles)} más</button>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
