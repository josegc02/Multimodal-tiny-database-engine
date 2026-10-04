# Mapa espacial

El panel **Mapa espacial** inicia una API HTTP local en `127.0.0.1` y el botón
**Abrir mapa** carga una página Leaflet con tiles de OpenStreetMap. No requiere
dependencias Python adicionales. El frontend nunca expone el servidor fuera de
la máquina local.

Cada `SELECT` sobre una tabla con una columna `POINT` publica todos sus puntos y
resalta los identificadores incluidos en el resultado. Las consultas por radio
dibujan el centro y el círculo; `WITHIN(..., POLYGON(...))` dibuja el polígono.
Al hacer click, el mapa inserta `POINT(lat, lon)` en el editor SQL para completar
una consulta. Leaflet actualiza el estado una vez por segundo, por lo que las
consultas nuevas se reflejan sin recargar la pestaña.

Para usarlo:

```sql
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
```

Después se pulsa **Abrir mapa**. El acceso a tiles y al CDN de Leaflet requiere
conexión a Internet en el navegador; los datos de la tabla y la API se sirven
localmente. La prueba HTTP se omite solo en entornos que prohíben sockets locales.
