import { cp, lstat, mkdir, mkdtemp, readdir, rename, rm } from "node:fs/promises";
import { watch } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const root = fileURLToPath(new URL("../", import.meta.url));
const source = path.join(root, "src");
const dist = path.join(root, "dist");

async function copyModules(directory, output) {
  await mkdir(output, { recursive: true });
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) throw new Error("Source symlinks are not supported");
    if (entry.name === "templetes" || entry.name === "styles") continue;
    const input = path.join(directory, entry.name);
    const target = path.join(output, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "assets") await cp(input, target, { recursive: true });
      else await copyModules(input, target);
    } else if (entry.name.endsWith(".js")) await cp(input, target);
  }
}

function buildCss(output) {
  return new Promise((resolve, reject) => {
    const cli = path.join(root, "node_modules", "@tailwindcss", "cli", "dist", "index.mjs");
    const child = spawn(process.execPath, [cli, "-i", path.join(source, "input.css"), "-o", path.join(output, "app.css"), "--minify"], { cwd: root, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", code => code === 0 ? resolve() : reject(new Error(`CSS build failed: ${code}`)));
  });
}

export async function build() {
  const staging = await mkdtemp(path.join(root, ".dist-build-"));
  try {
    const templates = path.join(source, "pages", "templetes");
    for (const entry of await readdir(templates, { withFileTypes: true })) {
      if (!entry.isFile() || !entry.name.endsWith(".html")) throw new Error("Templates must be flat HTML files");
      await cp(path.join(templates, entry.name), path.join(staging, entry.name));
    }
    await copyModules(source, staging);
    await buildCss(staging);
    const current = await lstat(dist).catch(error => {
      if (error.code !== "ENOENT") throw error;
      return null;
    });
    if (current && (!current.isDirectory() || current.isSymbolicLink())) throw new Error("dist must be a generated directory, not a symlink");
    // Only replace this project's explicit generated output, after a successful build.
    await rm(dist, { recursive: true, force: true });
    await rename(staging, dist);
  } finally {
    await rm(staging, { recursive: true, force: true });
  }
}

async function watchSource() {
  let pending = false;
  let building = false;
  let timer;
  async function rebuild() {
    if (building) { pending = true; return; }
    building = true;
    try { await build(); console.log("Frontend rebuilt"); }
    catch (error) { console.error(error.message); }
    finally {
      building = false;
      if (pending) { pending = false; await rebuild(); }
    }
  }
  const watcher = watch(source, { recursive: true }, () => {
    clearTimeout(timer);
    timer = setTimeout(rebuild, 100);
  });
  watcher.on("error", error => {
    clearTimeout(timer);
    watcher.close();
    console.error("Source watch failed:", error.message);
    process.exitCode = 1;
  });
  await rebuild();
  console.log("Watching HTML, JS and CSS source changes");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes("--watch")) await watchSource();
  else await build();
}
