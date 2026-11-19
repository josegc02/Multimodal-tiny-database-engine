import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import { entero } from './formato.js';
import { guardarReciente, leerRecientes } from './historial.js';
import { IconoBiblioteca, IconoMenu, IconoPreguntar, IconoSubir, Marca } from './Iconos.jsx';
import { enlace, ir, useRuta } from './ruta.js';
import Preguntar from './asistente/Preguntar.jsx';
import Biblioteca from './asistente/Biblioteca.jsx';
import Documento from './asistente/Documento.jsx';
import Subir from './asistente/Subir.jsx';

export default function App() {
  const ruta = useRuta();
  const [recientes, setRecientes] = useState(leerRecientes);
  const [estado, setEstado] = useState(null);       // GET /asistente/estado
  const [errorEstado, setErrorEstado] = useState(null);
  const [menuAbierto, setMenuAbierto] = useState(false);
  const [borrador, setBorrador] = useState('');      // pregunta sugerida desde otra vista

  const cargarEstado = useCallback(() => {
    api.estado().then((e) => { setEstado(e); setErrorEstado(null); }).catch(setErrorEstado);
  }, []);
  useEffect(cargarEstado, [cargarEstado]);
  useEffect(() => setMenuAbierto(false), [ruta]);

  const alResponder = (datos) => {
    const { id, lista } = guardarReciente(datos);
    setRecientes(lista);
    return id;
  };
  const preguntarSobre = (texto) => { setBorrador(texto); ir(enlace.preguntar); };

  const reciente = ruta.reciente ? recientes.find((r) => r.id === ruta.reciente) : null;
  const titulos = { preguntar: 'Preguntar', biblioteca: 'Biblioteca', documento: 'Documento', subir: 'Subir PDF' };
  const actual = (vista) => (ruta.vista === vista || (vista === 'biblioteca' && ruta.vista === 'documento') ? 'page' : undefined);

  return (
    <div className="app">
      <header className="cabecera-movil">
        <Marca tamano={22} />
        <strong>{titulos[ruta.vista]}</strong>
        <button aria-label="Abrir el menú" aria-expanded={menuAbierto} onClick={() => setMenuAbierto(true)}><IconoMenu /></button>
      </header>

      <aside className="barra" data-abierta={menuAbierto}>
        <div className="marca">
          <Marca />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="marca-nombre">Asistente BD2</span>
            <span className="marca-curso">CS2042 · Bases de Datos II · 2026-2</span>
          </div>
          {menuAbierto && <button className="btn2" style={{ marginLeft: 'auto' }} onClick={() => setMenuAbierto(false)}>Cerrar</button>}
        </div>

        <nav className="nav" aria-label="Secciones">
          <a href={enlace.preguntar} aria-current={actual('preguntar')}><IconoPreguntar />Preguntar</a>
          <a href={enlace.biblioteca} aria-current={actual('biblioteca')}>
            <IconoBiblioteca />Biblioteca<span className="cuenta num">{estado?.documentos ?? ''}</span>
          </a>
          <a href={enlace.subir} aria-current={actual('subir')}><IconoSubir />Subir PDF</a>
        </nav>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="grupo-titulo">Recientes</span>
          <div className="recientes">
            {recientes.length === 0 && <span className="vacio">Tus preguntas aparecerán aquí.</span>}
            {recientes.map((r) => (
              <a key={r.id} href={enlace.reciente(r.id)} title={r.pregunta}
                 aria-current={ruta.reciente === r.id ? 'page' : undefined}>{r.pregunta}</a>
            ))}
          </div>
        </div>

        <div className="motor">
          <strong>Motor</strong>
          {errorEstado && <span style={{ color: 'var(--negativo)' }}>La API no responde</span>}
          {estado && !estado.corpus && <span>Sin corpus: carga los papers con rag.corpus</span>}
          {estado?.corpus && <span className="num">{entero(estado.documentos)} documentos · {entero(estado.fragmentos)} fragmentos</span>}
          {estado?.corpus && <span>Índice SPIMI en fragmentos.texto</span>}
          {estado && (
            <span>
              <span className="punto" style={{ background: estado.llm ? 'var(--positivo)' : 'var(--gris)' }} />
              {estado.llm ?? 'Sin LLM: solo fragmentos'}
            </span>
          )}
        </div>
      </aside>

      <main className="contenido">
        {ruta.vista === 'preguntar' && (
          <Preguntar key={ruta.reciente ?? ruta.auto ?? 'nueva'} reciente={reciente} auto={ruta.auto} estado={estado}
                     borrador={borrador} limpiarBorrador={() => setBorrador('')} alResponder={alResponder} />
        )}
        {ruta.vista === 'biblioteca' && <Biblioteca />}
        {ruta.vista === 'documento' && <Documento id={ruta.id} preguntarSobre={preguntarSobre} />}
        {ruta.vista === 'subir' && <Subir alSubir={cargarEstado} preguntarSobre={preguntarSobre} />}
      </main>
    </div>
  );
}
