import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { execSync } from 'node:child_process';
import { defineConfig } from 'vitest/config';

// The API is FastAPI (backend/app). In development Vite serves the page and proxies these paths to it; in production
// FastAPI serves the built page (frontend/dist) at /ui/ next to the same API, so the page never names a host.
const API = process.env.TIDEALERT_API ?? 'http://127.0.0.1:8000';
const API_PATHS = ['/runs', '/map', '/cases', '/tasks', '/responders', '/copilot', '/needs', '/pledges', '/reports', '/validation', '/gauges', '/relief'];

// DEV SERVER ONLY (apply: 'serve'; absent from a build): the commit now checked out, read at each request, for the Full Demo's pre-flight
// ("is the running API built from this commit?"). Nothing in the production bundle refers to it.
const demoSha = {
  name: 'demo-sha',
  apply: 'serve' as const,
  configureServer(server: { config: { base: string }; middlewares: { use(path: string, fn: (req: unknown, res: { setHeader(k: string, v: string): void; end(b: string): void }) => void): void } }) {
    server.middlewares.use(`${server.config.base}__demo/sha`, (_req, res) => {
      let sha: string | null = null;
      try { sha = execSync('git rev-parse HEAD', { encoding: 'utf8', timeout: 5000 }).trim(); } catch { /* not a git checkout */ }
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ sha }));
    });
  },
};

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss(), demoSha],
  server: { proxy: Object.fromEntries(API_PATHS.map((p) => [p, API])) },
  // MapLibre alone is ~800 kB minified (~220 kB gzipped); one chunk is fine for this page.
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: 'node' },
});
