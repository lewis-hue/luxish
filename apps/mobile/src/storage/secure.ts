/**
 * Credential storage.
 *
 * Tokens go to the platform keychain/keystore via `expo-secure-store` and nowhere
 * else — never AsyncStorage, never the SQLite outbox, never a log line. §18 requires
 * it, and `expo-secure-store` is the only store here backed by hardware-protected
 * keys.
 *
 * SDK 58 notes: the module is unavailable on web, so the store falls back to
 * memory there rather than throwing — the web build is a preview target and
 * must not crash on a storage call. See `memory` below for why that is a
 * fallback and not a no-op, and why it is not `localStorage`. `requireAuthentication` is deliberately not used: it does
 * not work in Expo Go, and a biometric prompt on every API call is the wrong
 * trade for a 5-minute access token.
 */

import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * Deliberately NOT derived from the brand name, even though ADR-002 routes every
 * other user-visible string through `branding.config.js`.
 *
 * A keychain key is a storage address, not a label. If it tracked the display name,
 * the rebrand this project is explicitly expecting would change every key and
 * silently sign out every existing install — a migration nobody would think to
 * write. So these use the stable package namespace, which ADR-002 keeps independent
 * of the brand for exactly this reason.
 */
const KEYS = {
  accessToken: 'fashion.auth.access_token',
  refreshToken: 'fashion.auth.refresh_token',
  /** Expiry as epoch milliseconds, so a token can be refreshed before it is used. */
  accessTokenExpiry: 'fashion.auth.access_token_expires_at',
} as const;

/** Keychain service name; groups our items so account deletion can clear them all. */
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainService: 'fashion.auth',
};

const supported = Platform.OS !== 'web';

/**
 * The web fallback: tokens held in memory, for the life of the tab.
 *
 * **Not a no-op, and not `localStorage`.** Reads and writes both used to do
 * nothing on web, which did not degrade gracefully so much as break
 * sign-in outright: the session published `signedIn` from memory, the first
 * API call asked for a token, found none stored, treated that as a revoked
 * session and signed the user straight back out. Signing in and being
 * ejected one request later is not a reduced experience, it is a broken one.
 *
 * `localStorage` would fix it and is the wrong fix: §18 keeps credentials out
 * of any store a script on the page can read, and web here is a preview
 * target rather than a shipping surface. A module-scoped map is readable by
 * the same page either way, but it is not persisted, so it leaves nothing
 * behind after the tab closes and nothing for a later XSS to find. The cost
 * is that a reload signs you out, which is the correct trade for a preview.
 */
const memory = new Map<string, string>();

async function read(key: string): Promise<string | null> {
  if (!supported) return memory.get(key) ?? null;
  try {
    return await SecureStore.getItemAsync(key, OPTIONS);
  } catch {
    // A corrupt or inaccessible keychain item must read as "signed out" rather
    // than crash the app on launch.
    return null;
  }
}

async function write(key: string, value: string | null): Promise<void> {
  if (!supported) {
    if (value === null) memory.delete(key);
    else memory.set(key, value);
    return;
  }
  if (value === null) {
    await SecureStore.deleteItemAsync(key, OPTIONS);
    return;
  }
  await SecureStore.setItemAsync(key, value, OPTIONS);
}

export interface StoredSession {
  accessToken: string;
  refreshToken: string | null;
  /** Epoch milliseconds. */
  expiresAt: number | null;
}

export const secureSession = {
  async load(): Promise<StoredSession | null> {
    const accessToken = await read(KEYS.accessToken);
    if (!accessToken) return null;
    const expiry = await read(KEYS.accessTokenExpiry);
    return {
      accessToken,
      refreshToken: await read(KEYS.refreshToken),
      expiresAt: expiry ? Number(expiry) : null,
    };
  },

  async save(session: StoredSession): Promise<void> {
    await write(KEYS.accessToken, session.accessToken);
    await write(KEYS.refreshToken, session.refreshToken);
    await write(
      KEYS.accessTokenExpiry,
      session.expiresAt === null ? null : String(session.expiresAt),
    );
  },

  /** Signing out, and the 401 path. Clears every key, not just the access token. */
  async clear(): Promise<void> {
    await Promise.all(Object.values(KEYS).map((key) => write(key, null)));
  },

  /**
   * Access token if it is present and not about to expire.
   *
   * The 30-second margin matters: a token that passes a bare `expiresAt > now`
   * check can still expire in flight, producing a 401 that looks like a revoked
   * session rather than an expired one.
   */
  async validAccessToken(now: number = Date.now()): Promise<string | null> {
    const session = await this.load();
    if (!session) return null;
    if (session.expiresAt !== null && session.expiresAt - 30_000 <= now) return null;
    return session.accessToken;
  },

  /** Exposed for tests and for the account-deletion flow. */
  keys: KEYS,
};
