/**
 * Refreshes openapi.json from a running API.
 *
 * The document is committed deliberately: the mobile build must not depend on a
 * backend being reachable, and a diff in this file is the visible signal that a
 * contract changed. `npm run check` fails when the committed types drift from the
 * document, so a schema change cannot land without the client being regenerated.
 */
import { writeFile } from 'node:fs/promises';

const url = process.env.API_SPEC_URL ?? 'http://127.0.0.1:8010/openapi.json';

const response = await fetch(url);
if (!response.ok) {
  console.error(`could not read ${url}: ${response.status} ${response.statusText}`);
  console.error('start the API first, or set API_SPEC_URL.');
  process.exit(1);
}

const spec = await response.json();
await writeFile('openapi.json', `${JSON.stringify(spec, null, 2)}\n`);
console.log(`wrote openapi.json — ${Object.keys(spec.paths).length} paths from ${url}`);
