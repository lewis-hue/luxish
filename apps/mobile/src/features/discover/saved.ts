import Store from 'expo-sqlite/kv-store';
import { useCallback, useEffect, useState } from 'react';

/**
 * Saved looks and favourite garments.
 *
 * `expo-sqlite/kv-store` rather than AsyncStorage: on SDK 58 it is the drop-in
 * replacement with the same API, backed by SQLite, and it offers synchronous reads.
 * That matters here because a save toggle that waits on async storage flickers from
 * unsaved to saved on every mount.
 *
 * Local-only for now, deliberately: there is no authenticated session yet, so
 * writing these to the API would mean inventing an anonymous identity. They migrate
 * to the server at sign-in. What must not happen is a saved item silently
 * disappearing at that point, so the keys are stable and the stored shape is the one
 * the API will accept.
 */

const SAVED_LOOKS = 'fashion.saved_looks';
const FAVOURITE_GARMENTS = 'fashion.favourite_garments';

function readSet(key: string): Set<string> {
  try {
    const raw = Store.getItemSync(key);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    // A corrupt value reads as empty rather than crashing the screen using it.
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

function useStoredSet(key: string) {
  const [values, setValues] = useState<Set<string>>(() => readSet(key));

  useEffect(() => {
    const listener = () => setValues(readSet(key));
    const existing = listeners.get(key) ?? new Set<() => void>();
    existing.add(listener);
    listeners.set(key, existing);
    return () => {
      existing.delete(listener);
    };
  }, [key]);

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

/** Looks the user kept for inspiration. */
export function useSavedLooks() {
  return useStoredSet(SAVED_LOOKS);
}

/**
 * Garments the user marked as favourites.
 *
 * A *stated* preference, not an inference, which is why it is stored explicitly and
 * weighted by the stylist. "Clothes I actually love" is information no amount of
 * wear-history guessing reproduces reliably, and asking is cheaper than modelling.
 */
export function useFavouriteGarments() {
  return useStoredSet(FAVOURITE_GARMENTS);
}

/** Read favourites outside React — the stylist request builder needs them. */
export function favouriteGarmentIds(): readonly string[] {
  return [...readSet(FAVOURITE_GARMENTS)];
}

export const STORAGE_KEYS = {
  savedLooks: SAVED_LOOKS,
  favouriteGarments: FAVOURITE_GARMENTS,
} as const;
