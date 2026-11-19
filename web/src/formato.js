// Formatos compartidos por las vistas del asistente.
const numeros = new Intl.NumberFormat('en-US');

export const entero = (n) => (n == null ? '—' : numeros.format(n));

export const TEMAS = {
  semilla: 'Clásicos', curso: 'Clase del curso', subido: 'Subido', ann_grafos: 'ANN con grafos',
  cuantizacion_ivf: 'Cuantización e IVF', lsh: 'LSH', bd_vectoriales: 'BD vectoriales',
  bm25_indice_invertido: 'BM25 e índice invertido', recuperacion_densa: 'Recuperación densa',
  recuperacion_dispersa: 'Recuperación dispersa', rag: 'RAG', indices_espaciales: 'Índices espaciales',
  indices_aprendidos: 'Índices aprendidos', estructuras_disco: 'Estructuras en disco',
  optimizacion_consultas: 'Optimización de consultas',
};

export const esClase = (documento) => documento.fuente === 'curso';

/** "Clase 09", o el apellido del primer autor (y "et al." si hay más de dos). */
export function referencia(documento) {
  if (esClase(documento)) return (documento.titulo ?? '').split(':')[0];
  const autores = (documento.autores ?? '').split(';').map((a) => a.trim()).filter(Boolean);
  const apellido = (a) => a.split(' ').slice(-1)[0];
  if (autores.length === 0) return 'Sin autor';
  if (autores.length === 1) return apellido(autores[0]);
  if (autores.length === 2) return `${apellido(autores[0])} y ${apellido(autores[1])}`;
  return `${apellido(autores[0])} et al.`;
}

/** "diaps. 14–23" en una clase, "pp. 2–3" en un paper. */
export function paginas(f, clase) {
  const fin = f.pagina_fin && f.pagina_fin !== f.pagina ? f.pagina_fin : null;
  if (clase) return fin ? `diaps. ${f.pagina}–${fin}` : `diap. ${f.pagina}`;
  return fin ? `pp. ${f.pagina}–${fin}` : `p. ${f.pagina}`;
}

export function autoresCortos(autores) {
  const lista = (autores ?? '').split(';').map((a) => a.trim()).filter(Boolean);
  return lista.length > 3 ? `${lista.slice(0, 3).join(', ')} y otros ${lista.length - 3}` : lista.join(', ');
}

// Las portadas de las clases traen el correo del docente: no se muestra. Las viñetas de
// las diapositivas (○ ■ ● ▪) se quitan: en un fragmento corrido solo estorban.
export const sinCorreos = (texto) => (texto ?? '')
  .replace(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, '')
  .replace(/\s*[○■●▪•◦]\s*/g, ' ')
  .replace(/\s{2,}/g, ' ')
  .trim();

/** Parte la respuesta del LLM en párrafos con trozos de texto y citas [n]. */
export function partirRespuesta(texto) {
  return (texto ?? '').split(/\n\s*\n/).map((parrafo) =>
    parrafo.split(/(\[\d+(?:\s*,\s*\d+)*\])/).filter(Boolean).flatMap((trozo) => {
      const cita = trozo.match(/^\[(\d+(?:\s*,\s*\d+)*)\]$/);
      if (!cita) return [{ texto: trozo }];
      return cita[1].split(',').map((n) => ({ cita: Number(n) }));
    }),
  );
}
