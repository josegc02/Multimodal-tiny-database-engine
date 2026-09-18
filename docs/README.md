# Documentación del Proyecto

La documentación e informe técnico del proyecto se encuentran organizados en este directorio:

* [**`informe.md`**](informe.md): Informe técnico incremental del proyecto (arquitectura, decisiones de diseño, algoritmos y resultados experimentales).
* [**`sql_grammar.ebnf`**](sql_grammar.ebnf): Gramática formal del dialecto SQL soportado.
* [**`sql_parser.md`**](sql_parser.md): Diseño del parser, contrato del AST y límites del análisis sintáctico.

---

### Resumen: Implementación de Heap File con Slotted Pages

* **Páginas fijas de 4096 bytes (4 KB)**: Alineadas con el tamaño de bloque del sistema operativo y sectores de disco para máxima eficiencia de I/O.
* **Header (4 bytes)**: Almacena `num_slots` (2B) y `data_end` (2B).
* **Crecimiento bidireccional**: Los datos crecen hacia adelante desde el byte 4, mientras que el directorio de slots (5 bytes por slot: `offset`, `length`, `is_deleted`) crece hacia atrás desde el final de la página (byte 4096).
* **Espacio libre continuo**: El espacio disponible se concentra en el medio (`slot_dir_start - data_end`), evitando fragmentación y desplazamientos de memoria.
* **Estabilidad de RIDs**: El uso de slots fijos y eliminación lógica (`is_deleted = 1`) garantiza que las direcciones `RID(page_id, slot_id)` sean inmutables, permitiendo indexación secundaria confiable con árboles B+ y Hash Dinámico.
* **Reutilización inteligente**: Recicla slots eliminados antes de consumir nuevo espacio contiguo en disco.
