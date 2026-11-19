import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// El puerto 5173 es el que la API permite por CORS (BD2_CORS_ORIGINS).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
