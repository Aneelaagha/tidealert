import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The API is FastAPI (backend/app). In development Vite serves the page and proxies these paths to it; in production
// FastAPI serves the built page (frontend/dist) at /ui/ next to the same API, so the page never names a host.
const API = process.env.TIDEALERT_API ?? 'http://127.0.0.1:8000';
const API_PATHS = ['/runs', '/map', '/cases', '/tasks', '/responders', '/copilot', '/needs', '/pledges', '/reports', '/validation'];

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  server: { proxy: Object.fromEntries(API_PATHS.map((p) => [p, API])) },
  // MapLibre alone is ~800 kB minified (~220 kB gzipped); one chunk is fine for this page.
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: 'node' },
});
