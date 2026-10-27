import * as Crypto from 'expo-crypto';
import Store from 'expo-sqlite/kv-store';
import { useCallback, useEffect, useState } from 'react';

import { slotFor, type Slot } from '@/features/taxonomy';

import { SAMPLE_WARDROBE, type Availability, type SampleGarment } from './sample';
import { awaitProcessing, canSync, uploadGarment } from './sync';

/**
 * The user's own garments, held on the device and synced when there is a
 * session to attach them to.
 *
 * Local-*first*, not local-only. A photograph is written here the moment it is
 * taken and is visible immediately, then uploaded in the background; the
 * server's answer (slot, category, colour, cut-out) is merged back when it
 * arrives. Someone signed out, on a plane, or behind a dead API still has a
 * working wardrobe, and their photographs are not lost waiting for one.
 *
 * The stored shape is deliberately the one the API accepts, so signing in
 * later is an upload rather than a translation.
 *
 * Added garments and the sample wardrobe are kept in separate lists and merged on
 * read. That way "clear the sample" never risks touching a real photograph, and a
 * user's first real garment is visibly theirs rather than appearing among
 * demonstration items.
 */

const KEY = 'fashion.wardrobe_items';

export interface UserGarment {
  id: string;
  name: string;
  /** Local file URI until uploaded; replaced by a delivered URL afterwards. */
  localUri: string;
  /** Set once background removal has produced a clean cut-out. */
  cleanedUri?: string | null;
  slot: Slot;
  categoryId: string | null;
  /**
   * What a model read from the photo, with its confidence. Never merged into
   * confirmed values — a user correction must always win (ADR-010), and that is
   * only possible if the two are stored apart.
   */
  inferred?: { colour?: string; pattern?: string; material?: string } | null;
  inferenceConfidence?: number | null;
  /** What the user stated. Outranks `inferred` key by key. */
  confirmed?: { colour?: string; category?: string } | null;
  availability: Availability;
  isFavourite: boolean;
  /** Pending until the categorisation job has run. */
  status: 'pending' | 'ready' | 'failed';
  addedAt: number;
  /**
   * The server's id, once this garment has been uploaded.
   *
   * Its absence is what marks a garment as not yet synced, so a device that
   * was offline or signed out when the photo was taken can send it later
   * without a separate queue to keep in step.
   */
  serverId?: string | null;
  /** Why the last sync attempt failed, for the user rather than the log. */
  syncError?: string | null;
}

function read(): UserGarment[] {
  try {
    const raw = Store.getItemSync(KEY);
    return raw ? (JSON.parse(raw) as UserGarment[]) : [];
  } catch {
    // A corrupt list reads as empty rather than bricking the wardrobe screen.
    return [];
  }
}

async function write(items: UserGarment[]): Promise<void> {
  await Store.setItemAsync(KEY, JSON.stringify(items));
}

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

/** A garment as the wardrobe grid renders it, whatever its origin. */
export interface WardrobeEntry {
  /** Not yet uploaded. Shown so a user knows what the stylist cannot see. */
  needsSync?: boolean;
  /** Why the last upload failed, in words a person can act on. */
  syncError?: string | null;
  id: string;
  name: string;
  slot: Slot;
  categoryId: string | null;
  availability: Availability;
  isFavourite: boolean;
  isSample: boolean;
  status: 'pending' | 'ready' | 'failed';
  /** Bundled asset handle for samples. */
  image?: number | null;
  /** File or remote URI for user photos. */
  uri?: string | null;
  blurhash?: string | null;
}

function sampleToEntry(garment: SampleGarment, favourites: Set<string>): WardrobeEntry {
  return {
    id: garment.id,
    name: garment.name,
    slot: slotFor(garment.category) ?? 'accessories',
    categoryId: garment.category,
    availability: garment.availability,
    isFavourite: favourites.has(garment.id),
    isSample: true,
    status: 'ready',
    image: garment.image,
    blurhash: garment.blurhash,
  };
}

function userToEntry(garment: UserGarment): WardrobeEntry {
  return {
    id: garment.id,
    name: garment.name,
    slot: garment.slot,
    categoryId: garment.categoryId,
    availability: garment.availability,
    isFavourite: garment.isFavourite,
    isSample: false,
    status: garment.status,
    // Prefer the cut-out once it exists; the original is kept and never replaced.
    uri: garment.cleanedUri ?? garment.localUri,
    blurhash: null,
    needsSync: !garment.serverId,
    syncError: garment.syncError ?? null,
  };
}

export function useWardrobe(favourites: Set<string>) {
  const [items, setItems] = useState<UserGarment[]>(() => read());

  useEffect(() => {
    const listener = () => setItems(read());
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  /** User garments first — someone's own clothes should not sit below the demo. */
  const entries: WardrobeEntry[] = [
    ...items.map(userToEntry),
    ...SAMPLE_WARDROBE.map((garment) => sampleToEntry(garment, favourites)),
  ].map((entry) =>
    entry.isSample ? entry : { ...entry, isFavourite: favourites.has(entry.id) },
  );

  const addMany = useCallback(
    async (
      photos: readonly { uri: string; suggestedName: string | null }[],
    ): Promise<string[]> => {
      const now = Date.now();
      const added: UserGarment[] = photos.map((photo, index) => ({
        id: `g-${Crypto.randomUUID()}`,
        // A placeholder name the user can edit. Guessing from a filename like
        // "IMG_4821" would be worse than saying plainly that it is new.
        name: photo.suggestedName?.trim() || `New item ${index + 1}`,
        localUri: photo.uri,
        cleanedUri: null,
        slot: 'tops',
        categoryId: null,
        inferred: null,
        inferenceConfidence: null,
        confirmed: null,
        availability: 'available',
        isFavourite: false,
        // Categorisation runs server-side; until then the item exists and is
        // visible rather than being hidden behind a spinner.
        status: 'pending',
        addedAt: now + index,
      }));

      const next = [...added, ...read()];
      await write(next);
      notify();

      // Fire and forget. The garment is already on screen, and making the
      // tap wait on a network round trip plus two paid model calls would
      // make adding clothes feel broken on a slow connection.
      void syncAll(added);

      return added.map((garment) => garment.id);
    },
    [],
  );

  const rename = useCallback(async (id: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    await write(read().map((item) => (item.id === id ? { ...item, name: trimmed } : item)));
    notify();
  }, []);

  const setAvailability = useCallback(async (id: string, availability: Availability) => {
    await write(read().map((item) => (item.id === id ? { ...item, availability } : item)));
    notify();
  }, []);

  const remove = useCallback(async (id: string) => {
    await write(read().filter((item) => item.id !== id));
    notify();
  }, []);

  return { entries, items, addMany, rename, setAvailability, remove };
}

/**
 * Upload the garments that have no server id yet, and merge back what the
 * server works out about them.
 *
 * Each is independent: one failing upload must not stop the rest, because a
 * single unreadable photograph would otherwise block every garment behind it.
 * Failures are recorded on the garment rather than thrown, so the wardrobe
 * can show which ones need attention instead of a modal nobody can act on.
 */
export async function syncAll(
  candidates: readonly UserGarment[] = read(),
): Promise<void> {
  const pending = candidates.filter((item) => !item.serverId);
  if (pending.length === 0) return;
  if (!(await canSync())) return;

  await Promise.all(
    pending.map(async (item) => {
      try {
        const serverId = await uploadGarment({
          uri: item.localUri,
          name: item.name,
        });
        patch(item.id, { serverId, syncError: null });

        const result = await awaitProcessing(serverId);
        patch(item.id, {
          slot: result.slot,
          categoryId: result.categoryId,
          cleanedUri: result.cleanedUri,
          inferred: result.inferred,
          inferenceConfidence: result.inferenceConfidence,
          status: result.status,
        });
      } catch (error) {
        // Not `failed`: the photograph is intact and the upload can be
        // retried. Marking it failed would imply the garment is unusable.
        patch(item.id, {
          syncError:
            error instanceof Error ? error.message : 'Could not sync this item.',
        });
      }
    }),
  );
}

/** Merge fields into one garment, by id. Writes and notifies. */
function patch(id: string, fields: Partial<UserGarment>): void {
  void write(
    read().map((item) => (item.id === id ? { ...item, ...fields } : item)),
  ).then(notify);
}

/** Read outside React — the stylist request builder needs the real wardrobe. */
export function wardrobeItems(): readonly UserGarment[] {
  return read();
}

export const WARDROBE_STORAGE_KEY = KEY;
