import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir, access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../../", import.meta.url));
async function files(dir) { const result = []; for (const entry of await readdir(dir, { withFileTypes: true })) { const file = path.join(dir, entry.name); if (entry.isDirectory()) result.push(...await files(file)); else result.push(file); } return result; }
test("one Vue SPA entry replaces the per-page HTML/script entrypoints", async () => {
 const html = await readFile(path.join(root, "index.html"), "utf8");
 assert.equal([...html.matchAll(/<script\b/g)].length, 1);
 assert.match(html, /src="\/src\/main.ts"/);
 const pages = await files(path.join(root, "src/pages"));
 assert.ok(pages.some(file => file.endsWith("LoginPage.vue")));
 assert.ok(!pages.some(file => /\.(html|js)$/.test(file)));
});
test("legacy entrypoints and DOM rendering implementations are retired", async () => {
 for (const name of ["src/pages/keys.js", "src/shared/http/client.js", "scripts/build.mjs", "src/app.js", "src/admin.js", "src/admin-users.js", "src/branding.js"]) assert.equal(await access(path.join(root, name)).then(() => true, () => false), false, name);
 const source = await files(path.join(root, "src"));
 for (const file of source.filter(file => /\.(vue|ts)$/.test(file))) { const text = await readFile(file, "utf8"); assert.ok(!/innerHTML|v-html|localStorage/.test(text), file); }
});
test("Vue modules use a typed build and explicit lazy page routing", async () => {
 const pkg = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
 assert.ok(pkg.dependencies.vue && pkg.dependencies["vue-router"]);
 assert.match(pkg.scripts.build, /vue-tsc.*vite build/);
 const routes = await readFile(path.join(root, "src/router/index.ts"), "utf8");
 for (const file of ["KeysPage.vue", "ReportsPage.vue", "OverviewPage.vue", "SettingsPage.vue", "UsersPage.vue"]) assert.ok(routes.includes(file));
 assert.ok(routes.includes("authorizeRoute"));
});
test("production publishes compiled hashed assets, never tests/source/private config", async () => {
 const dist = path.join(root, "dist"), output = (await files(dist)).map(file => path.relative(dist, file));
 assert.equal(output.filter(file => file.endsWith(".html")).join(), "index.html");
 assert.ok(!output.some(file => /(^|\/)(tests|scripts|node_modules|templetes|styles)(\/|$)|\.(vue|ts|map)$|\.env/.test(file)));
 const html = await readFile(path.join(dist, "index.html"), "utf8");
 const source = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)]; assert.equal(source.length, 1); assert.match(source[0][1], /^\/assets\/.+-[\w-]+\.js$/);
 await access(path.join(dist, source[0][1]));
 const css = await readFile(path.join(dist, output.find(file => file.endsWith(".css"))), "utf8");
 for (const selector of [".console-shell", ".app-modal", ".login-layout", ".metric-grid", ".notice"]) assert.ok(css.includes(selector), selector);
});
test("Docker context includes the Vue build inputs and publishes only dist", async () => {
 const docker = await readFile(path.join(root, 'Dockerfile'), 'utf8');
 const ignore = await readFile(path.join(root, '.dockerignore'), 'utf8');
 assert.match(docker, /FROM node:24-bookworm-slim AS build/);
 for (const name of ['index.html', 'vite.config.ts', 'tsconfig.json', 'package.json', 'package-lock.json']) assert.ok(ignore.includes('!' + name), name);
 assert.ok(ignore.includes('!src/**'));
 assert.match(docker, /COPY index.html vite.config.ts tsconfig.json/);
 assert.match(docker, /COPY --from=build \/build\/frontend\/dist \/usr\/share\/nginx\/html/);
 assert.ok(!docker.includes('scripts/build.mjs'));
});
