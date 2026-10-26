// Isolated frontend test double. Never imported by the app or production server.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
const root = new URL('../../web/', import.meta.url);
http.createServer(async (req, res) => {
  const files = { '/': ['index.html','text/html'], '/app.js': ['app.js','text/javascript'], '/pdf.js': ['pdf.js','text/javascript'], '/style.css': ['style.css','text/css'] };
  const file = files[req.url];
  if (!file) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': file[1], 'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" });
  res.end(await readFile(new URL(file[0],root)));
}).listen(8766,'127.0.0.1',() => console.log('Frontend-only test server: http://127.0.0.1:8766 (API must be explicitly mocked in tests)'));
