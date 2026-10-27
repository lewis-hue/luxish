/**
 * A release build must never point at a loopback or cleartext API.
 *
 * This existed as a real defect: the dev URL sat in eas.json's shared `base` env,
 * which `production` extends, so a production build would have shipped pointing at
 * `http://127.0.0.1:8010`. It fails silently — the app installs, launches, and every
 * request times out — so a test is the only thing that catches it before a store
 * review does.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

type Profile = {
  extends?: string;
  env?: Record<string, string>;
};

const easJson = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', 'eas.json'), 'utf8'),
) as { build: Record<string, Profile> };

/** Resolves a profile's env the way EAS does, following `extends`. */
function resolvedEnv(name: string): Record<string, string> {
  const profile = easJson.build[name];
  if (!profile) throw new Error(`no such build profile: ${name}`);
  const inherited = profile.extends ? resolvedEnv(profile.extends) : {};
  return { ...inherited, ...(profile.env ?? {}) };
}

const SHIPPING_PROFILES = ['preview', 'production'] as const;
const DEV_PROFILES = ['development', 'simulator'] as const;

describe('EAS build profiles', () => {
  it.each(SHIPPING_PROFILES)('%s points at an https API', (name) => {
    const url = resolvedEnv(name).EXPO_PUBLIC_API_BASE_URL;
    expect(url).toBeDefined();
    expect(url).toMatch(/^https:\/\//);
  });

  it.each(SHIPPING_PROFILES)('%s never points at a loopback or LAN address', (name) => {
    const url = resolvedEnv(name).EXPO_PUBLIC_API_BASE_URL ?? '';
    // 10.0.2.2 is the Android emulator's alias for the host — equally wrong in a
    // shipped build, and easy to leave behind after local testing.
    expect(url).not.toMatch(/127\.0\.0\.1|localhost|10\.0\.2\.2|192\.168\./);
  });

  it('keeps the loopback URL out of the shared base profile', () => {
    // The actual defect: anything in `base` is inherited by production.
    expect(easJson.build.base?.env?.EXPO_PUBLIC_API_BASE_URL).toBeUndefined();
  });

  it.each(DEV_PROFILES)('%s is a development client so it can hot-reload', (name) => {
    expect(easJson.build[name]).toMatchObject({ developmentClient: true });
  });

  it('builds on an even-numbered Node version', () => {
    // ADR-014: RN 0.88 / SDK 58 exclude odd-numbered Node releases, so a build
    // pinned to 25.x would fail in a way that looks like a dependency problem.
    const node = (easJson.build.base as { node?: string }).node ?? '';
    const major = Number(node.split('.')[0]);
    expect(Number.isInteger(major)).toBe(true);
    expect(major % 2).toBe(0);
  });
});
