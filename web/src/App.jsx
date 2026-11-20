import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { entero } from './formato.js';
import { guardarReciente, leerRecientes } from './historial.js';
import { IconoBiblioteca, IconoMenu, IconoPreguntar, IconoSubir, Marca } from './Iconos.jsx';
import { conFiltros, enlace, ir, useRuta } from './ruta.js';
import Preguntar from './asistente/Preguntar.jsx';
import Biblioteca from './asistente/Biblioteca.jsx';
import Documento from './asistente/Documento.jsx';
import Subir from './asistente/Subir.jsx';

export default function App() {
  const [ruta, reemplazarRuta] = useRuta();
  const [recientes, setRecientes] = useState(leerRecientes);
  const [filtroHistorial, setFiltroHistorial] = useState('');
  const [estado, setEstado] = useState(null);       // GET /asistente/estado
  const [errorEstado, setErrorEstado] = useState(null);
  const [menuAbierto, setMenuAbierto] = useState(false);
  const abrirMenu = useRef(null);
  const cerrarMenu = useRef(null);
  const debeDevolverFoco = useRef(false);
  const { vista, id, auto, reciente: idReciente } = ruta;
  const [borrador, setBorrador] = useState('');      // pregunta sugerida desde otra vista

  const cargarEstado = useCallback(() => {
    api.estado().then((e) => { setEstado(e); setErrorEstado(null); }).catch(setErrorEstado);
  }, []);
  useEffect(cargarEstado, [cargarEstado]);
  useEffect(() => setMenuAbierto(false), [vista, id, auto, idReciente]);
  useEffect(() => {
    if (!menuAbierto) {
      if (debeDevolverFoco.current) abrirMenu.current?.focus();
      debeDevolverFoco.current = false;
      return undefined;
    }
    debeDevolverFoco.current = true;
    cerrarMenu.current?.focus();
    const movil = window.matchMedia('(max-width: 900px)');
    const alRedimensionar = (evento) => {
      if (!evento.matches) {
        debeDevolverFoco.current = false;
        setMenuAbierto(false);
      }
    };
    movil.addEventListener('change', alRedimensionar);
    return () => movil.removeEventListener('change', alRedimensionar);
  }, [menuAbierto]);

  function tecladoMenu(evento) {
    if (!menuAbierto) return;
    if (evento.key === 'Escape') {
      evento.preventDefault();
      setMenuAbierto(false);
      return;
    }
    if (evento.key !== 'Tab') return;
    const elementos = evento.currentTarget.querySelectorAll('button, a[href], input');
    const primero = elementos[0];
    const ultimo = elementos[elementos.length - 1];
    if (evento.shiftKey && document.activeElement === primero) {
      evento.preventDefault();
      ultimo.focus();
    } else if (!evento.shiftKey && document.activeElement === ultimo) {
      evento.preventDefault();
      primero.focus();
    }
  }

  const alResponder = (datos) => {
    const { id, lista } = guardarReciente(datos);
    setRecientes(lista);
    return id;
  };
  const preguntarSobre = (texto) => { setBorrador(texto); ir(enlace.preguntar); };

  const consultasVisibles = recientes.filter((item) => item.pregunta.toLowerCase().includes(filtroHistorial.trim().toLowerCase()));
  const reciente = ruta.reciente ? recientes.find((r) => r.id === ruta.reciente) : null;
  const volverBiblioteca = conFiltros(enlace.biblioteca, ruta.filtros);
  const titulos = { preguntar: 'Preguntar', biblioteca: 'Biblioteca', documento: 'Documento', subir: 'Subir PDF' };
  const actual = (vista) => (ruta.vista === vista || (vista === 'biblioteca' && ruta.vista === 'documento') ? 'page' : undefined);

  return (
    <div className="app">
      <header className="cabecera-movil" inert={menuAbierto ? '' : undefined}>
        <Marca tamano={22} />
        <strong>{titulos[ruta.vista]}</strong>
        <button ref={abrirMenu} aria-controls="menu-asistente" aria-label="Abrir el menú" aria-expanded={menuAbierto} onClick={() => setMenuAbierto(true)}><IconoMenu /></button>
      </header>

      <aside id="menu-asistente" className="barra" data-abierta={menuAbierto}
             role={menuAbierto ? 'dialog' : undefined} aria-modal={menuAbierto || undefined}
             aria-label={menuAbierto ? 'Menú del asistente' : undefined} onKeyDown={tecladoMenu}>
        <div className="marca">
          <Marca />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span className="marca-nombre">Asistente BD2</span>
            <span className="marca-curso">CS2042 · Bases de Datos II · 2026-2</span>
          </div>
          {menuAbierto && <button ref={cerrarMenu} className="btn2" style={{ marginLeft: 'auto' }} onClick={() => setMenuAbierto(false)}>Cerrar</button>}
        </div>

        <nav className="nav" aria-label="Secciones">
          <a href={enlace.preguntar} onClick={() => setMenuAbierto(false)} aria-current={actual('preguntar')}><IconoPreguntar />Preguntar</a>
          <a href={volverBiblioteca} onClick={() => setMenuAbierto(false)} aria-current={actual('biblioteca')}>
            <IconoBiblioteca />Biblioteca<span className="cuenta num">{estado?.documentos ?? ''}</span>
          </a>
          <a href={enlace.subir} onClick={() => setMenuAbierto(false)} aria-current={actual('subir')}><IconoSubir />Subir PDF</a>
        </nav>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <h2 className="grupo-titulo">Historial</h2>
          {recientes.length > 0 && (
            <input type="search" className="buscar-historial" aria-label="Buscar en el historial"
                   placeholder="Buscar preguntas" value={filtroHistorial} onChange={(e) => setFiltroHistorial(e.target.value)} />
          )}
          <div className="recientes">
            {recientes.length === 0 && <span className="vacio">Tus preguntas aparecerán aquí.</span>}
            {recientes.length > 0 && consultasVisibles.length === 0 && <span className="vacio" role="status">Ninguna pregunta coincide.</span>}
            {consultasVisibles.map((r) => (
              <a key={r.id} href={enlace.reciente(r.id)} title={r.pregunta} onClick={() => setMenuAbierto(false)}
                 aria-current={ruta.reciente === r.id ? 'page' : undefined}>{r.pregunta}</a>
            ))}
          </div>
        </div>

        <div className="motor">
          <strong>Estado del asistente</strong>
          {errorEstado && <span style={{ color: '#ffadb4' }}>Servidor sin conexión</span>}
          {estado && !estado.corpus && <span>Biblioteca sin documentos</span>}
          {estado?.corpus && <span className="num">{entero(estado.documentos)} documentos · {entero(estado.fragmentos)} fragmentos</span>}
          {estado && (
            <span>
              {estado.llm ? `Modelo configurado: ${estado.llm}` : 'Modo búsqueda: solo fragmentos'}
            </span>
          )}
        </div>
      </aside>

      <main className="contenido" inert={menuAbierto ? '' : undefined}>
        {ruta.vista === 'preguntar' && (
          <Preguntar key={ruta.reciente ?? ruta.auto ?? 'nueva'} reciente={reciente} auto={ruta.auto}
                     borrador={borrador} limpiarBorrador={() => setBorrador('')} alResponder={alResponder} />
        )}
        {ruta.vista === 'biblioteca' && <Biblioteca filtros={ruta.filtros} cambiarRuta={reemplazarRuta} />}
        {ruta.vista === 'documento' && <Documento id={ruta.id} volverBiblioteca={volverBiblioteca} preguntarSobre={preguntarSobre} />}
        {ruta.vista === 'subir' && <Subir alSubir={cargarEstado} preguntarSobre={preguntarSobre} />}
      </main>
    </div>
  );
}
