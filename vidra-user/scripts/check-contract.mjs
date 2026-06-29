#!/usr/bin/env node
// Frontend <-> backend contract drift guard.
//
// The vidra-user API client (lib/api/*.ts) hand-maintains the paths it calls on
// vidra-core. Nothing currently fails when the backend renames/removes an endpoint
// the frontend still calls (types.ts is marked PROVISIONAL, no codegen). This script
// is the interim guard: it asserts every /api/ path the frontend references exists
// in vidra-core's OpenAPI spec. Path params are compared structurally ({id} vs
// {videoId} both normalize to {}), so it is name-agnostic and not flaky. It does NOT
// check HTTP methods or field shapes — that needs generated types (a later step).
//
// Run: node vidra-user/scripts/check-contract.mjs   (exit 1 on drift)

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");
const OPENAPI = join(repoRoot, "vidra-core", "api", "openapi.yaml");
const API_DIR = join(repoRoot, "vidra-user", "lib", "api");

// Collapse path params and trailing noise so /api/v1/videos/{id} (backend) and
// /api/v1/videos/${encodeURIComponent(id)} (frontend) compare equal.
function normalize(p) {
  return p
    .replace(/\$\{[^}]*\}/g, "{}") // ${encodeURIComponent(id)} -> {}
    .replace(/\{[^}]*\}/g, "{}") // {id} / {handle} -> {}
    .replace(/\?.*$/, "") // strip any query string
    .replace(/\/+$/, ""); // strip trailing slash
}

// Path keys under `paths:` are the only 2-space-indented `/...:` lines in the spec.
function backendPaths(yaml) {
  const set = new Set();
  let inPaths = false;
  for (const line of yaml.split("\n")) {
    if (/^paths:\s*$/.test(line)) {
      inPaths = true;
      continue;
    }
    if (inPaths && /^\S/.test(line)) inPaths = false; // next top-level key ends the section
    const m = inPaths && line.match(/^ {2}(\/\S+):\s*$/);
    if (m) set.add(normalize(m[1]));
  }
  return set;
}

// Every string/template literal containing /api/ in the frontend API client.
function frontendRefs(content, file) {
  const refs = [];
  content.split("\n").forEach((line, i) => {
    const strRe = /(['"`])((?:\\.|(?!\1).)*?)\1/g;
    let m;
    while ((m = strRe.exec(line)) !== null) {
      const hit = m[2].match(/\/api\/[^\s?'"`]*/);
      if (hit) refs.push({ norm: normalize(hit[0]), raw: hit[0], file, line: i + 1 });
    }
  });
  return refs;
}

const backend = backendPaths(readFileSync(OPENAPI, "utf8"));
if (backend.size === 0) {
  console.error("contract: could not extract any paths from", OPENAPI);
  process.exit(2);
}

const refs = [];
for (const f of readdirSync(API_DIR)) {
  if (!f.endsWith(".ts") || f.endsWith(".test.ts")) continue;
  refs.push(...frontendRefs(readFileSync(join(API_DIR, f), "utf8"), f));
}

const missing = refs.filter((r) => !backend.has(r.norm));
const referenced = new Set(refs.map((r) => r.norm));

console.log(`contract: ${backend.size} backend paths, ${referenced.size} referenced by the frontend client`);
if (missing.length) {
  console.error("\n❌ Frontend calls paths that do NOT exist in vidra-core/api/openapi.yaml:");
  for (const r of missing) console.error(`  ${r.raw}  (${r.file}:${r.line})  -> normalized ${r.norm}`);
  console.error("\nFix the frontend path, or update the backend OpenAPI spec to match.");
  process.exit(1);
}

console.log("✅ Every frontend-referenced path exists in the backend OpenAPI contract.");
