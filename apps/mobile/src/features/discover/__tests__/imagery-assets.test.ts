/**
 * Every picture the app asks for has to exist on disk.
 *
 * `require('@/assets/...')` is resolved by Metro at bundle time, so a
 * missing file is not a blank tile or a caught error — it is a red screen
 * that takes the whole app down before the first render, with a message
 * naming a line in `imagery.ts` rather than the missing picture.
 *
 * It happened: a batch of covers was being regenerated, the stale files
 * were deleted first, and Metro resolved a `require` in the gap between
 * the delete and the write. The bundle has no way to recover from that,
 * and neither typecheck nor lint can see it — a `require` of a missing
 * asset is valid TypeScript.
 *
 * So this walks the real strings and stats the real files. It is the only
 * check in the suite that touches the asset directory, and it is worth the
 * exception: it is also the only one that can catch this.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const IMAGERY = join(__dirname, '..', 'imagery.ts');
const ASSETS = join(__dirname, '..', '..', '..', '..', 'assets', 'images');

/** Pull every bundled asset path out of the module's source. */
function referencedAssets(): string[] {
  // Read rather than import: importing evaluates the `require` calls, which
  // is the very thing being checked and which jest resolves differently
  // from Metro anyway.
  const source = readFileSync(IMAGERY, 'utf8');
  const found = source.matchAll(/@\/assets\/images\/([A-Za-z0-9/_-]+\.(?:webp|png|jpg))/g);
  return [...new Set([...found].map((match) => match[1]))];
}

describe('bundled imagery', () => {
  const referenced = referencedAssets();

  it('references at least the full cover set', () => {
    // A guard on the guard: a regex that silently stopped matching would
    // make this suite pass by checking nothing.
    expect(referenced.length).toBeGreaterThan(100);
  });

  it.each(referenced)('%s exists', (relative) => {
    expect(existsSync(join(ASSETS, relative))).toBe(true);
  });
});
