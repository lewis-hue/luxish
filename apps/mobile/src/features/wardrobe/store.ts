import * as Crypto from 'expo-crypto';
import Store from 'expo-sqlite/kv-store';
import { useCallback, useEffect, useState } from 'react';

import { useMe } from '@/api/queries/me';
import { slotFor, type Slot } from '@/features/taxonomy';

import { SAMPLE_WARDROBE, type Availability, type SampleGarment } from './sample';
import {
  awaitProcessing,
  canSync,
  fetchCutout,
  fetchServerGarments,
  uploadGarment,
} from './sync';

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

/**
 * Whose garments the stored list belongs to.
 *
 * **One device, more than one account.** The list lived under a
 * single key with nothing saying whose it was, and nothing cleared it
 * on sign-out - so signing out of one account and into another left
 * the first person's clothes on screen for the second. Their names,
 * their photographs, on somebody else's wardrobe page. A local-first
 * store does not get to skip the question the server answers on every
 * request.
 *
 * The owner is recorded beside the items and checked the moment the
 * signed-in account is known. A mismatch empties the list rather than
 * merging it: the new account's own garments come down from the
 * server by `pull`, and nothing of the previous one is kept.
 */
const OWNER_KEY = 'fashion.wardrobe_owner';

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
  /**
   * Placeholder shown while the picture loads.
   *
   * ThumbHash rather than BlurHash, and the reason is alpha. BlurHash is RGB
   * only, so a cut-out garment's transparent surround averages into a muddy
   * block and the placeholder reads as a dirty smear in the shape of a tile.
   * ThumbHash carries alpha at the same cost, so the transparent region stays
   * transparent and the placeholder looks like the garment arriving.
   *
   * Only for the user's own garments. The bundled style covers are opaque
   * photographs with no alpha to lose, so BlurHash is correct for them and
   * regenerating them would buy nothing.
   */
  thumbhash?: string | null;
  /**
   * True when the picture is a rendering rather than a photograph.
   *
   * A garment can be plainly visible in a photo and impossible to cut out of
   * it, so it is drawn from what was read off it instead. The wardrobe says
   * so: a drawing of a garment like yours is not evidence you own that one.
   */
  isRendered?: boolean;
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

/** Who the stored list belongs to, if anybody has claimed it. */
function storedOwner(): string | null {
  try {
    // Empty is unclaimed, not "owned by nobody-in-particular".
    // `forgetWardrobe` writes an empty string, and reading that back
    // as an owner made the next sign-in look like a different person
    // and wipe a list that was already empty.
    return Store.getItemSync(OWNER_KEY) || null;
  } catch {
    return null;
  }
}

/**
 * Hand the local wardrobe to this account, emptying it if it was
 * somebody else's.
 *
 * Called as soon as the signed-in user is known. Returns true when it
 * cleared somebody else's list, so the caller can pull a fresh one.
 *
 * An unclaimed list is adopted rather than discarded: it predates
 * this bookkeeping and almost certainly belongs to the only person
 * who has used this device. Adopting it keeps their garments; the
 * ownership stamp then stops it being handed to the next account.
 */
export async function claimWardrobe(userId: string): Promise<boolean> {
  const owner = storedOwner();
  if (owner === userId) return false;

  const foreign = owner !== null && owner !== userId;
  if (foreign) {
    await Store.setItemAsync(KEY, JSON.stringify([]));
  }
  await Store.setItemAsync(OWNER_KEY, userId);
  if (foreign) notify();
  return foreign;
}

/**
 * Forget this device's wardrobe. Called on sign-out.
 *
 * The server keeps every synced garment, so signing back in restores
 * them; what goes is the copy sitting on a device somebody else may
 * be about to use.
 */
export async function forgetWardrobe(): Promise<void> {
  await Store.setItemAsync(KEY, JSON.stringify([]));
  await Store.setItemAsync(OWNER_KEY, '');
  notify();
}


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
  /** Alpha-aware placeholder for a user garment's cut-out. */
  thumbhash?: string | null;
  /**
   * The server's id, where this garment has one. Carried so a screen can act
   * on the server copy — hearting it, for instance — without reaching back
   * into the store to look it up.
   */
  serverId?: string | null;
  /** True when the picture is a rendering rather than a photograph. */
  isRendered?: boolean;
  /**
   * What a model read off the photograph. Carried onto the grid entry so
   * search can match on it: someone looking for "denim" should find the
   * jeans they named "work trousers".
   */
  inferred?: { colour?: string; pattern?: string; material?: string } | null;
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
    serverId: garment.serverId ?? null,
    thumbhash: garment.thumbhash ?? null,
    syncError: garment.syncError ?? null,
    isRendered: garment.isRendered ?? false,
    inferred: garment.inferred ?? null,
  };
}

/**
 * Fetch cut-outs for garments that do not have one yet.
 *
 * Background removal runs on its own queue and can finish after the
 * upload flow has returned - or after the app was closed part-way
 * through it. Without this sweep those garments keep the photograph
 * their owner took, bed and all, for ever: the job succeeded, the
 * server has the cut-out, and nothing on the device ever asked for it.
 *
 * Quiet and best-effort. A garment with its own photograph is perfectly
 * usable, so a failure here changes nothing visible and is not worth
 * surfacing.
 */
export async function pullMissingCutouts(): Promise<number> {
  const current = read();
  const waiting = current.filter(
    (item) => item.serverId && !item.cleanedUri && item.status === 'ready',
  );
  if (waiting.length === 0) return 0;

  let filled = 0;
  for (const item of waiting) {
    try {
      const uri = await fetchCutout(item.serverId as string);
      if (uri) {
        patch(item.id, { cleanedUri: uri });
        filled += 1;
      }
    } catch (error) {
      if (__DEV__) {
        console.warn('[wardrobe] could not fetch a cut-out', item.id, error);
      }
    }
  }
  return filled;
}

export function useWardrobe(favourites: Set<string>) {
  const [items, setItems] = useState<UserGarment[]>(() => read());
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const listener = () => setItems(read());
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  /**
   * Take anything the server has that this device does not.
   *
   * The device is not the only author of this wardrobe. Outfit detection
   * creates a garment per piece it finds in a photograph, and those exist
   * only on the server, so a wardrobe built purely from local records is
   * missing every garment the product's headline feature produces.
   *
   * Never throws. Being offline or signed out means the wardrobe shows what
   * is on the device, which is the whole point of keeping it there.
   */
  const pull = useCallback(async (): Promise<number> => {
    if (!(await canSync())) return 0;
    try {
      const adopted = await adoptServerGarments();
      // And the pictures for garments whose cut-out landed after their
      // upload finished. Separate from adoption because these are
      // garments the device already has: what is missing is the
      // picture, not the row.
      await pullMissingCutouts();
      return adopted;
    } catch (error) {
      if (__DEV__) {
        console.warn('[wardrobe] could not read the server wardrobe', error);
      }
      return 0;
    }
  }, []);

  /**
   * The same pull, with the spinner a person expects when they ask for it.
   *
   * Separate from `pull` because the two are different events. Someone who
   * drags the list down has asked a question and is owed an answer they can
   * see; the pull on mount is housekeeping, and a spinner for it would
   * announce work on a wardrobe that is already on screen and already right.
   */
  const refresh = useCallback(async (): Promise<number> => {
    setRefreshing(true);
    try {
      return await pull();
    } finally {
      setRefreshing(false);
    }
  }, [pull]);

  // Whose device this is, before anything is shown from it.
  //
  // The list is local, so nothing about it is scoped by a request the
  // way a server read is. This is the scoping: the moment the signed
  // in account is known, the stored list is either theirs or it is
  // emptied.
  const me = useMe(true);
  const owner = me.data?.userId ?? null;

  /**
   * Whose list the one in `items` has been confirmed to be.
   *
   * **Nothing local is shown before this matches.** The first version
   * of this wiped a foreign list once the account was known, which
   * left a window - the whole of it, if `useMe` was slow, and for
   * ever if it never answered - where the previous person's clothes
   * were on screen. A control that protects somebody's things cannot
   * be the thing that waits on a network call.
   */
  const [claimedFor, setClaimedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!owner) return;
    let alive = true;
    void (async () => {
      await claimWardrobe(owner);
      // Theirs comes down from the server either way; after a wipe it
      // is the only thing that will put anything back.
      await pull();
      if (!alive) return;
      setItems(read());
      setClaimedFor(owner);
    })();
    return () => {
      alive = false;
    };
  }, [owner, pull]);

  // On mount, so opening the wardrobe shows what actually exists. A garment
  // detected while the app was closed would otherwise never appear.
  useEffect(() => {
    void pull();
  }, [pull]);

  /** User garments first — someone's own clothes should not sit below the demo. */
  // Until ownership is settled, this device has no garments to show.
  //
  // Fails closed on purpose: signed out, offline, or simply before
  // `/auth/me` has answered, the honest answer about whose clothes
  // these are is "not known yet" - and the safe rendering of that is
  // none of them, not all of them. The sample wardrobe stays, because
  // it belongs to nobody and is labelled as a demonstration.
  const mine = owner !== null && claimedFor === owner ? items : [];

  const entries: WardrobeEntry[] = [
    ...mine.map(userToEntry),
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
        // Deliberately not 'pending'. That state means "the server is working
        // on this", and showing it before anything has been uploaded is a
        // spinner that spins forever when the user is signed out: the sync
        // returns early, nothing changes, and the garment claims to be
        // sorting for the rest of its life. `serverId` being absent is what
        // says "not uploaded yet", and the grid labels that honestly.
        status: 'ready',
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

  return { entries, items, addMany, rename, setAvailability, remove, refresh, refreshing };
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

  if (!(await canSync())) {
    // Signed out. Say so on each garment rather than returning quietly: the
    // photographs are safe and will upload after sign-in, but the user needs
    // to know why nothing is happening, and a silent return is how a queue
    // becomes invisible.
    for (const item of pending) {
      patch(item.id, { syncError: 'Sign in to upload this.' });
    }
    return;
  }

  await Promise.all(
    pending.map(async (item) => {
      try {
        // 'pending' from here: the upload has genuinely started, so the
        // spinner now means what it says.
        patch(item.id, { status: 'pending', syncError: null });

        const serverId = await uploadGarment({
          uri: item.localUri,
          name: item.name,
        });
        patch(item.id, { serverId, syncError: null });

        const result = await awaitProcessing(serverId);

        // The photograph held several garments, so the server replaced this
        // row with one per piece. Drop the local garment and take what the
        // server has: keeping it would leave a picture of the user sitting in
        // their wardrobe beside the clothes detected in it.
        if (result.status === 'replaced') {
          await adoptServerGarments({ drop: item.id });
          return;
        }

        patch(item.id, {
          slot: result.slot,
          categoryId: result.categoryId,
          cleanedUri: result.cleanedUri,
          inferred: result.inferred,
          inferenceConfidence: result.inferenceConfidence,
          isRendered: result.isRendered,
          status: result.status,
        });
      } catch (error) {
        // The grid gets one short line, which is the right amount for someone
        // using the app and useless for working out why an upload failed. The
        // whole error goes to the console as well, where it is readable.
        // `__DEV__` is compiled away, so a release build logs nothing.
        if (__DEV__) {
          console.error('[wardrobe] sync failed', item.id, error);
        }
        // Not `failed`: the photograph is intact and the upload can be
        // retried. Marking it failed would imply the garment is unusable.
        // Back to 'ready' so the spinner stops; the error is what the grid
        // shows instead.
        patch(item.id, {
          status: 'ready',
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

/**
 * Take every garment the server holds that this device does not have.
 *
 * Needed because the device is not the only author of a wardrobe. Outfit
 * detection creates a garment per piece it finds in one photograph, and those
 * exist only on the server; without this they are detected, categorised,
 * cut out, and never seen.
 *
 * Matched on the server id, so running this twice adds nothing twice, and a
 * garment the device already knows about keeps its local photograph rather
 * than being replaced by a downloaded copy of the same thing.
 */
export async function adoptServerGarments(
  options: { drop?: string } = {},
): Promise<number> {
  const remote = await fetchServerGarments();
  const current = read().filter((item) => item.id !== options.drop);
  const known = new Set(
    current.map((item) => item.serverId).filter(Boolean) as string[],
  );

  const adopted: UserGarment[] = remote
    .filter((garment) => !known.has(garment.serverId))
    .map((garment) => ({
      id: `g-${garment.serverId}`,
      name: garment.name,
      // There is no photograph of this on the device; the server's picture is
      // the only one, and it has already been written to disk.
      localUri: garment.uri ?? '',
      cleanedUri: garment.uri,
      thumbhash: garment.thumbhash,
      slot: garment.slot,
      categoryId: garment.categoryId,
      inferred: garment.inferred,
      inferenceConfidence: garment.inferenceConfidence,
      isRendered: garment.isRendered,
      availability: 'available' as Availability,
      isFavourite: false,
      status: 'ready' as const,
      addedAt: Date.now(),
      serverId: garment.serverId,
      syncError: null,
    }));

  if (adopted.length === 0 && current.length === read().length) return 0;
  await write([...adopted, ...current]);
  notify();
  return adopted.length;
}
