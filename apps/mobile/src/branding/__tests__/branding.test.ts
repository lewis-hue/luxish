/**
 * ADR-002: a rebrand must be a one-file diff. The brand literal lives in
 * `branding.config.js` at the app root, read by both `app.config.ts` (native binary)
 * and `src/branding` (JS bundle). These tests enforce that nothing under `src/`
 * names the product, and that the derived identifiers stay consistent.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { BRAND } from '@/branding';

const SRC = join(__dirname, '..', '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      return entry === '__tests__' ? [] : sourceFiles(full);
    }
    return /\.(ts|tsx)$/.test(entry) ? [full] : [];
  });
}

describe('branding', () => {
  it('keeps the working name out of src entirely', () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => /\bAtelier\b/i.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SRC, file).replace(/\\/g, '/'));
    expect(offenders).toEqual([]);
  });

  it('exposes the account-deletion URL Google Play requires', () => {
    // §13: must be reachable without installing the app.
    expect(BRAND.urls.accountDeletion).toMatch(/^https:\/\//);
  });

  it('declares every legal and support surface a store listing needs', () => {
    expect(BRAND.urls.privacy).toMatch(/^https:\/\//);
    expect(BRAND.urls.terms).toMatch(/^https:\/\//);
    expect(BRAND.urls.contentPolicy).toMatch(/^https:\/\//);
    expect(BRAND.support.url).toMatch(/^https:\/\//);
  });

  it('flags that the name is still a placeholder', () => {
    // Guards against shipping the working name as though it were decided.
    expect(BRAND.isWorkingName).toBe(true);
  });

  it('derives a scheme that is URI-safe and matches the slug', () => {
    // app.config.ts feeds this same value to the native `scheme`; a mismatch would
    // silently break every deep link and the incoming-share route.
    expect(BRAND.scheme).toBe(BRAND.slug);
    expect(BRAND.ids.scheme).toBe(BRAND.scheme);
    expect(BRAND.scheme).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it('derives bundle and package identifiers from the slug', () => {
    expect(BRAND.ids.iosBundle).toContain(BRAND.slug);
    expect(BRAND.ids.androidPackage).toContain(BRAND.slug);
  });

  it('has no static app.json competing with app.config.ts', () => {
    // Two config sources silently merge and are a recurring source of confusion.
    const entries = readdirSync(join(SRC, '..'));
    expect(entries).not.toContain('app.json');
    expect(entries).toContain('app.config.ts');
  });
});
