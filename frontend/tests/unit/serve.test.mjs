import test from "node:test";
import assert from "node:assert/strict";
import { staticPath, createFrontendServer } from "../../scripts/serve.mjs";

test("frontend owns explicit pages and safe assets only", () => {
  assert.equal(staticPath("/"), "index.html");
  assert.equal(staticPath("/admin/settings"), "index.html");
  assert.equal(staticPath("/assets/KeysPage-hashed.js"), "assets/KeysPage-hashed.js");
  for (const route of ["/missing", "/assets/../.env", "/assets/%2e%2e/.env", "/assets/%2fetc/passwd", "/assets/a%5cb", "/assets/login.html", "/assets/%00x"]) assert.equal(staticPath(route), null, route);
});

test("development proxy requires one explicit origin, never a client-selected URL", () => {
  for (const origin of ["file:///tmp", "http://user:pass@localhost", "http://localhost/path", "http://localhost/?q=1"]) assert.throws(() => createFrontendServer({ apiOrigin: origin }));
});
