import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dos apps en un proyecto: el asistente académico (index.html, opción A) y la tienda
// (tienda.html, opción B). Comparten el cliente de la API; cada una tiene su armazón.
// El puerto 5173 es el que la API permite por CORS (BD2_CORS_ORIGINS).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: {
    rollupOptions: {
      input: { asistente: resolve(__dirname, 'index.html'), tienda: resolve(__dirname, 'tienda.html') },
    },
  },
});
