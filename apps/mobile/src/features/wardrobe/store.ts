import * as Crypto from 'expo-crypto';
import Store from 'expo-sqlite/kv-store';
import { useCallback, useEffect, useState } from 'react';

import { slotFor, type Slot } from '@/features/taxonomy';

import { SAMPLE_WARDROBE, type Availability, type SampleGarment } from './sample';

/**
 * The user's own garments, held on the device.
 *
 * Local until there is a session to attach them to. Writing them to the API now
 * would mean inventing an anonymous identity, and the migration away from that is
 * worse than the migration from local storage. The stored shape is deliberately the
 * one the API accepts, so sign-in is an upload rather than a translation.
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

/** Read outside React — the stylist request builder needs the real wardrobe. */
export function wardrobeItems(): readonly UserGarment[] {
  return read();
}

export const WARDROBE_STORAGE_KEY = KEY;
