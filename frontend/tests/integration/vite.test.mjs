import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { createFixtureServer } from '../fixtures/server.mjs';

test('Vite serves deep links and preserves the fixed-origin API/CSRF proxy contract', async () => {
  const { server: api, state } = createFixtureServer();
  await new Promise((resolve, reject) => { api.once('error', reject); api.listen(0, '127.0.0.1', resolve); });
  const previous = process.env.API_ORIGIN;
  process.env.API_ORIGIN = `http://127.0.0.1:${api.address().port}`;
  let vite;
  try {
    const root = fileURLToPath(new URL('../../', import.meta.url));
    vite = await createServer({ root, configFile: root + 'vite.config.ts', server: { host: '127.0.0.1', port: 0, strictPort: true } });
    await vite.listen();
    const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
    for (const path of ['/login', '/keys', '/admin/settings', '/admin/users']) {
      const response = await fetch(base + path); assert.equal(response.status, 200); assert.match(await response.text(), /src\/main.ts/);
    }
    const csrf = await fetch(base + '/v1/auth/csrf'); assert.match(csrf.headers.get('set-cookie'), /laya_csrf=fixture/); await csrf.json();
    const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': 'fixture', Cookie: 'laya_csrf=fixture', Forwarded: 'for=spoofed', 'X-Real-IP': 'spoofed', 'X-Forwarded-For': 'spoofed' };
    const created = await fetch(base + '/v1/api-keys', { method: 'POST', headers, body: '{"name":"vite-synthetic"}' });
    assert.equal(created.status, 201); await created.json();
    assert.equal(state.requests.at(-1).csrf, 'fixture'); assert.equal(state.requests.at(-1).forwardedFor, '127.0.0.1'); assert.equal(state.requests.at(-1).forwarded, undefined);
    const metadata = await fetch(base + '/v1/metadata'); assert.equal(metadata.status, 429); assert.equal(metadata.headers.get('x-request-id'), 'fixture-call'); assert.equal(metadata.headers.get('retry-after'), '7'); await metadata.json();
    const missing = await fetch(base + '/v1/unknown'); assert.equal(missing.status, 404); assert.match(missing.headers.get('content-type'), /json/); await missing.json();
    const redirect = await fetch(base + '/v1/redirect', { redirect: 'manual' }); assert.equal(redirect.headers.get('location'), base + '/v1/auth/me'); await redirect.text();
  } finally {
    await vite?.close(); api.closeAllConnections(); await new Promise(resolve => api.close(resolve));
    if (previous === undefined) delete process.env.API_ORIGIN; else process.env.API_ORIGIN = previous;
  }
});
