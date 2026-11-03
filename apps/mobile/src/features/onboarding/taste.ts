import Store from 'expo-sqlite/kv-store';

/**
 * Whether this device has put the taste questions to somebody.
 *
 * Separate from whether they *answered*, and the difference is the whole
 * point. The server records the answers; this records that the question was
 * asked. Somebody who skipped has answered "no thanks", and asking again on
 * every launch turns a one-time question into nagging — the fastest way to
 * make a person dismiss something they might otherwise have filled in.
 *
 * Local rather than server-side on purpose: "has this device shown you the
 * screen" is a device fact. A second phone asking once is correct, because it
 * genuinely has not asked.
 *
 * Synchronous read, for the reason the welcome flag is read synchronously:
 * whatever decides to show this has to decide before the first paint.
 */

const KEY = 'fashion.taste_asked';

export function hasAskedTaste(): boolean {
  try {
    return Store.getItemSync(KEY) === 'true';
  } catch {
    // Unreadable storage means asking again, which is the harmless way to be
    // wrong: a repeated question beats never personalising at all.
    return false;
  }
}

export async function markTasteAsked(): Promise<void> {
  await Store.setItemAsync(KEY, 'true');
}

/** Test seam, and the way to re-offer the questions from a debug build. */
export async function resetTasteAsked(): Promise<void> {
  await Store.setItemAsync(KEY, 'false');
}
