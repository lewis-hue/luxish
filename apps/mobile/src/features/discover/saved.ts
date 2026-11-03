import Store from 'expo-sqlite/kv-store';
import { useCallback, useEffect, useState } from 'react';

/**
 * Saved looks and favourite garments, on the device.
 *
 * `expo-sqlite/kv-store` rather than AsyncStorage: on SDK 58 it is the drop-in
 * replacement with the same API, backed by SQLite, and it offers synchronous
 * reads. That matters here because a save toggle that waits on async storage
 * flickers from unsaved to saved on every mount.
 *
 * **This stayed the source of truth after the server gained a copy.** The
 * collection now persists against the account (`api/queries/saved.ts`), but
 * the local store is what the UI reads, so saving still works offline and the
 * bookmark still resolves synchronously. The server is a durable mirror that
 * survives a reinstall, not a round trip the tap waits on.
 *
 * **Looks carry the date they were kept; favourites do not.** A collection is
 * ordered and the order is something somebody built, so it has to survive the
 * migration — a whole local collection arriving at the server in one request
 * would otherwise stack into a single second. Favourites are a set with no
 * order to lose, so they stay a plain set.
 */

const FAVOURITE_GARMENTS = 'fashion.favourite_garments';

function readSet(key: string): Set<string> {
  try {
    const raw = Store.getItemSync(key);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

async function writeSet(key: string, values: Set<string>): Promise<void> {
  await Store.setItemAsync(key, JSON.stringify([...values]));
}

/** Subscribers, so two screens showing the same item stay in step. */
const listeners = new Map<string, Set<() => void>>();

function notify(key: string): void {
  listeners.get(key)?.forEach((listener) => listener());
}

function subscribe(key: string, listener: () => void): () => void {
  const existing = listeners.get(key) ?? new Set<() => void>();
  existing.add(listener);
  listeners.set(key, existing);
  return () => {
    existing.delete(listener);
  };
}

function useStoredSet(key: string) {
  const [values, setValues] = useState<Set<string>>(() => readSet(key));

  useEffect(() => subscribe(key, () => setValues(readSet(key))), [key]);

  const toggle = useCallback(
    async (id: string) => {
      const next = readSet(key);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      await writeSet(key, next);
      notify(key);
    },
    [key],
  );

  const has = useCallback((id: string) => values.has(id), [values]);

  return { values, has, toggle, count: values.size };
}

export function useFavouriteGarments() {
  return useStoredSet(FAVOURITE_GARMENTS);
}

/** Read favourites outside React — the stylist request builder needs them. */
export function favouriteGarmentIds(): readonly string[] {
  return [...readSet(FAVOURITE_GARMENTS)];
}

export const STORAGE_KEYS = {
  favouriteGarments: FAVOURITE_GARMENTS,
} as const;

/**
 * Forget which garments this device had marked as favourites.
 *
 * **Same reason the wardrobe is forgotten on sign-out.** This is a
 * set of ids kept against the device rather than the account, so
 * without clearing it the next person to sign in here inherits the
 * last person's hearts - on garments that are no longer even theirs.
 * Small beside a wardrobe full of photographs, and exactly the same
 * mistake.
 */
export async function forgetFavourites(): Promise<void> {
  await writeSet(FAVOURITE_GARMENTS, new Set());
}
