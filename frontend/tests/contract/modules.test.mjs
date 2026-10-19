import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir, access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const source = path.join(root, "src");
const templates = path.join(source, "pages", "templetes");
async function files(dir) {
  const result = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...await files(file));
    else result.push(file);
  }
  return result;
}

test("each HTML template loads exactly its own ES module", async () => {
  const expected = { "login.html": "login", "api-keys.html": "keys", "usage.html": "usage", "billing.html": "billing", "admin.html": "admin/overview", "admin-settings.html": "admin/settings", "admin-users.html": "admin/users" };
  expected["index.html"] = "index";
  assert.deepEqual((await readdir(templates)).sort(), Object.keys(expected).sort());
  for (const [name, page] of Object.entries(expected)) {
    const html = await readFile(path.join(templates, name), "utf8");
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
    assert.equal(scripts.length, 1, name);
    assert.match(scripts[0][1], /type="module"/);
    assert.ok(scripts[0][1].includes(`src="/assets/pages/${page}.js"`));
    assert.equal(scripts[0][2].trim(), "");
    await access(path.join(source, "pages", `${page}.js`));
  }
});

test("retired global entrypoints and misplaced root templates are absent", async () => {
  const names = await readdir(source);
  assert.ok(!names.some(name => name.endsWith(".html") || name.endsWith(".js")));
  const output = await readdir(path.join(root, "dist"));
  for (const name of ["app.js", "admin.js", "admin-users.js", "branding.js"]) assert.ok(!output.includes(name));
});

test("named imports resolve to real exports, including dollar-named helpers", async () => {
  for (const file of (await files(source)).filter(file => file.endsWith(".js"))) {
    const body = await readFile(file, "utf8");
    for (const match of body.matchAll(/import\s*\{([^}]+)\}\s*from\s*["']([^"']+)["']/g)) {
      assert.ok(match[2].startsWith("."), `${file}: browser imports must be relative`);
      const target = path.resolve(path.dirname(file), match[2]);
      assert.ok(target.startsWith(source + path.sep), target);
      const dependency = await readFile(target, "utf8");
      const names = new Set([...dependency.matchAll(/export\s+(?:async\s+)?(?:function|const|class)\s+([\w$]+)/g)].map(item => item[1]));
      for (const name of match[1].split(",").map(name => name.trim().split(/\s+as\s+/)[0])) {
        assert.ok(names.has(name), `${path.relative(source, file)} imports missing ${name} from ${match[2]}`);
      }
      if (file.includes(`${path.sep}shared${path.sep}`)) assert.ok(!target.includes(`${path.sep}pages${path.sep}`), "Shared modules cannot import pages");
    }
  }
});

test("dist flattens templates but preserves JS import paths and excludes development source", async () => {
  const dist = path.join(root, "dist");
  for (const name of await readdir(templates)) {
    assert.equal(await readFile(path.join(dist, name), "utf8"), await readFile(path.join(templates, name), "utf8"));
  }
  for (const file of (await files(source)).filter(file => file.endsWith(".js"))) {
    assert.equal(await readFile(path.join(dist, path.relative(source, file)), "utf8"), await readFile(file, "utf8"));
  }
  const output = (await files(dist)).map(file => path.relative(dist, file));
  assert.ok(!output.some(file => /(^|\/)(tests|scripts|node_modules|templetes|styles)(\/|$)/.test(file)));
  assert.ok(!output.includes("input.css"));
  const css = await readFile(path.join(dist, "app.css"), "utf8");
  for (const selector of [".console-shell", ".modal-overlay", ".login-layout", ".admin-metrics", ".bg-red-50", ".text-brand-500"]) assert.ok(css.includes(selector), selector);
});
