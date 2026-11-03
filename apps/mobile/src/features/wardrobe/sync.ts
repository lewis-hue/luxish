import { Image } from 'expo-image';
import { Directory, File, Paths } from 'expo-file-system';

import { api, ApiError, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';
import { NotSignedIn, uploadMedia } from '@/features/media/upload';
import { slotFor, type Slot } from '@/features/taxonomy';

/**
 * Getting a photographed garment to the server, and the result back.
 *
 * Four steps, in this order, because each depends on the one before:
 *
 *   1. authorise an upload, which creates the asset row and returns a capped,
 *      short-lived URL;
 *   2. PUT the bytes to it;
 *   3. create the garment against that asset, which queues categorisation and
 *      background removal;
 *   4. read the garment back until the jobs have run.
 *
 * **Local-first, not local-only.** A photograph is written to the device the
 * moment it is taken and is visible immediately; this runs afterwards, and a
 * failure anywhere leaves the garment exactly as it was. Someone who is
 * signed out, on a plane, or behind a dead API still has a working wardrobe,
 * which is the whole reason the local store exists rather than being a cache.
 *
 * Nothing here retries on its own. The queue it is handing work to is already
 * durable and already re-drives what it loses, so a second mechanism here
 * would duplicate uploads to solve a problem that is solved.
 */

/** What the server worked out about a garment once its jobs have run. */
export interface SyncedGarment {
  serverId: string;
  slot: Slot;
  categoryId: string | null;
  /** The cut-out, once background removal has produced one. */
  cleanedUri: string | null;
  /**
   * The server's id for that cut-out, when there is one.
   *
   * Carried separately from the URI because the two are produced at
   * different moments: the server knows the id as soon as the job
   * finishes, and the file only exists on the device once it has been
   * downloaded. Keeping only the URI is why a finished cut-out could
   * never be told apart from one that had not run.
   */
  cleanedAssetId: string | null;
  inferred: { colour?: string; pattern?: string; material?: string } | null;
  inferenceConfidence: number | null;
  /** True when the picture is a rendering rather than a photograph. */
  isRendered: boolean;
  /**
   * `replaced` means the server no longer has this garment under this id.
   *
   * It is the normal end of a photograph of someone wearing several things:
   * outfit detection creates one garment per piece and retires the row the
   * upload made, because leaving it would put a picture of the user in their
   * wardrobe next to the clothes from it. The id then stops resolving, which
   * is a success the client has to recognise, not the failure it looks like.
   */
  status: 'pending' | 'ready' | 'failed' | 'replaced';
}

/** One garment as the server holds it, with its picture already on disk. */
export interface ServerGarment {
  serverId: string;
  name: string;
  slot: Slot;
  categoryId: string | null;
  /** Local file URI for the best picture the server has of this garment. */
  uri: string | null;
  /** Alpha-aware placeholder computed from that picture. */
  thumbhash: string | null;
  inferred: { colour?: string; pattern?: string; material?: string } | null;
  inferenceConfidence: number | null;
  /** True when the picture is a rendering rather than a photograph. */
  isRendered: boolean;
}

// Re-exported, not redeclared: callers across the app already import it from
// here, and two classes of the same name would make `instanceof` depend on
// which module threw.
export { NotSignedIn };

/** True when there is a usable token, so callers can skip the whole path. */
export async function canSync(): Promise<boolean> {
  return (await accessToken()) !== null;
}


/**
 * Upload one photograph and create the garment it belongs to.
 *
 * Returns the server's garment id. The jobs it queues have not run yet, so
 * the caller polls separately rather than waiting here: categorisation and
 * segmentation each call a paid model and can take seconds, and blocking an
 * "add photo" tap on that would make the wardrobe feel broken.
 */
export async function uploadGarment(input: {
  uri: string;
  name: string;
}): Promise<string> {
  // The bytes go through the shared media upload, which is the only place
  // that knows how to get a photograph off this device intact — see
  // `features/media/upload.ts` for why each step there is the way it is.
  const asset_id = await uploadMedia({ uri: input.uri, kind: 'garment_photo' });


  const created = await api.POST('/v1/wardrobe/garments', {
    body: {
      name: input.name,
      media_asset_id: asset_id,
      // Required by the contract, and the right default: a garment someone
      // just photographed is one they can wear.
      availability: 'available',
    },
  });
  if (created.error || !created.data) {
    throw new Error('Could not create the garment.');
  }
  return created.data.id;
}

/**
 * Read a garment back until its jobs have run.
 *
 * Polls rather than holding a socket open: the work is queued and durable, so
 * the client asking again is both simpler and more robust than a connection
 * that has to survive a backgrounded app.
 */
/**
 * How many extra polls to spend waiting for a cut-out.
 *
 * Small. The garment is already usable without one, and the sweep on
 * the next wardrobe open is the real safety net; this only exists so
 * the common case shows the cut-out immediately rather than showing the
 * photograph and quietly replacing it later.
 */
const CUTOUT_ATTEMPTS = 6;

/** The same garment, with its cut-out downloaded if one exists. */
async function withCutout(garment: SyncedGarment): Promise<SyncedGarment> {
  if (!garment.cleanedAssetId) return garment;
  const token = await accessToken();
  if (!token) return garment;
  const uri = await downloadAsset(garment.cleanedAssetId, token);
  return uri ? { ...garment, cleanedUri: uri } : garment;
}

/**
 * Fetch the cut-out for one garment, if the server has made one.
 *
 * Used by the sweep that fills in garments whose cut-out landed after
 * the upload finished, or after the app was closed part-way through.
 */
export async function fetchCutout(serverId: string): Promise<string | null> {
  const token = await accessToken();
  if (!token) return null;
  const read = await api.GET('/v1/wardrobe/garments/{garment_id}', {
    params: { path: { garment_id: serverId } },
  });
  if (read.error || !read.data) return null;
  const assetId =
    ((read.data as Record<string, unknown>)
      .background_removed_asset_id as string | null) ?? null;
  return assetId ? await downloadAsset(assetId, token) : null;
}

export async function awaitProcessing(
  serverId: string,
  options: { attempts?: number; intervalMs?: number } = {},
): Promise<SyncedGarment> {
  const attempts = options.attempts ?? 20;
  const intervalMs = options.intervalMs ?? 1500;

  let last: SyncedGarment | null = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    let read;
    try {
      read = await api.GET('/v1/wardrobe/garments/{garment_id}', {
        params: { path: { garment_id: serverId } },
      });
    } catch (caught) {
      // A 404 here is not a failure. The garment was retired because the
      // photograph turned out to hold several, and the pieces are already in
      // the wardrobe on the server. Reported so the caller can go and get
      // them; anything else surfaces a successful detection as an error,
      // which is what it used to do.
      if (caught instanceof ApiError && caught.status === 404) {
        return { ...empty(serverId), status: 'replaced' };
      }
      throw caught;
    }
    if (read.error || !read.data) {
      throw new Error('Could not read the garment back.');
    }

    last = toSynced(serverId, read.data);
    // Categorisation is what decides the slot, so a category means the
    // first job has landed. The cut-out runs on a different queue and
    // usually lands within a few seconds of it, so once the garment has
    // settled this waits a little longer for the picture rather than
    // returning the photograph and never coming back for it.
    if (last.status !== 'pending') {
      if (last.cleanedAssetId) return await withCutout(last);
      for (let extra = 0; extra < CUTOUT_ATTEMPTS; extra += 1) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        const again = await api.GET('/v1/wardrobe/garments/{garment_id}', {
          params: { path: { garment_id: serverId } },
        });
        if (again.error || !again.data) break;
        const settled = toSynced(serverId, again.data);
        if (settled.cleanedAssetId) return await withCutout(settled);
        last = settled;
      }
      // Still not there. Not a failure: the sweep below picks it up the
      // next time the wardrobe opens.
      return last;
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  // Ran out of patience, not out of hope: the job is still queued and the
  // next read will find it. Reported as pending rather than failed.
  return last ?? { ...empty(serverId), status: 'pending' };
}

function empty(serverId: string): SyncedGarment {
  return {
    serverId,
    slot: 'tops',
    categoryId: null,
    cleanedUri: null,
    cleanedAssetId: null,
    inferred: null,
    inferenceConfidence: null,
    isRendered: false,
    status: 'pending',
  };
}

/** Map the API's garment onto what the local store holds. */
function toSynced(serverId: string, data: Record<string, unknown>): SyncedGarment {
  const category = (data.category as string | null) ?? null;
  const inferredRaw = (data.inferred_attributes ?? {}) as Record<string, unknown>;

  const colour = typeof inferredRaw.colour === 'string' ? inferredRaw.colour : undefined;
  const pattern =
    typeof inferredRaw.pattern === 'string' ? inferredRaw.pattern : undefined;
  const material =
    typeof inferredRaw.apparent_material === 'string'
      ? inferredRaw.apparent_material
      : undefined;

  // The classifier states the slot directly; `slotFor` is the fallback when
  // only a category came back, and 'tops' the last resort so a garment always
  // lands somewhere visible rather than vanishing from every filter.
  const slotValue = inferredRaw.slot;
  const slot: Slot =
    (typeof slotValue === 'string' ? (slotValue as Slot) : undefined) ??
    (category ? slotFor(category) : undefined) ??
    'tops';

  return {
    serverId,
    slot,
    categoryId: category,
    // Identifier, not URL. The server exposes the cut-out as an asset id
    // and the bytes are fetched separately, so the URI is filled in by
    // whoever downloads it - which, until this id was carried, was
    // nobody: the field sat at null for ever and every garment showed
    // the photograph its owner took, background and all.
    cleanedUri: null,
    cleanedAssetId:
      (data.background_removed_asset_id as string | null) ?? null,
    inferred:
      colour || pattern || material ? { colour, pattern, material } : null,
    // `inference_confidence` is the name on the wire. `categorisation_confidence`
    // is not a field, so this was always null.
    inferenceConfidence:
      typeof data.inference_confidence === 'number'
        ? data.inference_confidence
        : null,
    isRendered: data.image_is_rendered === true,
    status: category ? 'ready' : 'pending',
  };
}

/**
 * Where pictures the server derived are kept on the device.
 *
 * Downloaded once rather than fetched on every render. The delivery endpoint
 * needs a bearer token, and a token in an `Image` header is a token that
 * expires behind a cached picture; a file on disk has no such problem, keeps
 * the wardrobe working offline, and matches how a photograph taken on the
 * device is already handled.
 */
function garmentPictureDirectory(): Directory {
  const directory = new Directory(Paths.document, 'garments');
  if (!directory.exists) directory.create({ intermediates: true });
  return directory;
}

/**
 * Pull one asset down and return a file URI for it.
 *
 * Returns null rather than throwing: a garment with no picture is worth
 * showing, and one that failed to download is not worth losing the whole
 * reconciliation over.
 */
async function downloadAsset(assetId: string, token: string): Promise<string | null> {
  const target = new File(garmentPictureDirectory(), assetId);
  if (target.exists) return target.uri;
  try {
    const downloaded = await File.downloadFileAsync(
      `${API_BASE_URL}/v1/uploads/local/${assetId}`,
      target,
      { headers: { Authorization: `Bearer ${token}` }, idempotent: true },
    );
    return downloaded.uri;
  } catch (caught) {
    if (__DEV__) console.warn('[wardrobe] could not fetch picture', assetId, caught);
    return null;
  }
}

/**
 * Every garment the server holds for this user, pictures included.
 *
 * The device is the source of truth for photographs it took, and the server is
 * the source of truth for garments it derived — the pieces outfit detection
 * finds in one photograph exist only there. Without this the feature works
 * end to end on the server and is invisible on the phone.
 */
export async function fetchServerGarments(): Promise<ServerGarment[]> {
  const token = await accessToken();
  if (!token) throw new NotSignedIn();

  const listed = await api.GET('/v1/wardrobe/garments', {
    params: { query: { limit: 50 } },
  });
  if (listed.error || !listed.data) {
    throw new Error('Could not read the wardrobe.');
  }

  const items = (listed.data.items ?? []) as Record<string, unknown>[];
  return Promise.all(
    items.map(async (item) => {
      const synced = toSynced(String(item.id), item);
      // The cut-out when there is one, the photograph otherwise. A garment the
      // server derived always has a cut-out; one the user uploaded may not yet.
      const assetId =
        (item.background_removed_asset_id as string | null) ??
        (item.media_asset_id as string | null);
      const uri = assetId ? await downloadAsset(assetId, token) : null;
      return {
        serverId: String(item.id),
        name: typeof item.name === 'string' && item.name ? item.name : 'Garment',
        slot: synced.slot,
        categoryId: synced.categoryId,
        uri,
        thumbhash: uri ? await placeholderFor(uri) : null,
        inferred: synced.inferred,
        inferenceConfidence: synced.inferenceConfidence,
        isRendered: synced.isRendered,
      };
    }),
  );
}

/**
 * Tell the server which garments the user loves.
 *
 * It needs to know because the stylist orders its candidates by it: the
 * candidate list is capped, so in a wardrobe larger than the cap a favourite
 * that never reached the server is a garment the stylist is never shown.
 * Hearting something and then being handed outfits that ignore it is the
 * failure this prevents.
 *
 * Never throws. The heart is already filled in on the device and the local
 * store is the record; a failed push costs the stylist some context until the
 * next one, which is not worth interrupting someone's tap for.
 */
export async function pushFavourite(input: {
  serverId: string;
  isFavourite: boolean;
}): Promise<boolean> {
  if (!(await canSync())) return false;
  try {
    const call = input.isFavourite ? api.POST : api.DELETE;
    const sent = await call('/v1/wardrobe/garments/{garment_id}/favourite', {
      params: { path: { garment_id: input.serverId } },
    });
    return !sent.error;
  } catch (caught) {
    if (__DEV__) {
      console.warn('[wardrobe] could not sync favourite', input.serverId, caught);
    }
    return false;
  }
}

/**
 * A placeholder for a picture already on disk.
 *
 * ThumbHash rather than BlurHash because these are cut-outs: BlurHash cannot
 * represent alpha, so the transparent surround averages into a block of
 * colour and the placeholder reads as a smear rather than as the garment
 * arriving.
 *
 * Returns null rather than throwing. A garment with no placeholder shows an
 * empty tile for a moment, which is a smaller problem than a wardrobe that
 * fails to load because one picture would not hash. Android and iOS only —
 * on web it is simply absent.
 */
async function placeholderFor(uri: string): Promise<string | null> {
  try {
    return await Image.generateThumbhashAsync(uri);
  } catch (caught) {
    if (__DEV__) console.warn('[wardrobe] no placeholder for', uri, caught);
    return null;
  }
}
