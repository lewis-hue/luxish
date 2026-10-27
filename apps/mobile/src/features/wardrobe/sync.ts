import { api, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';
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
  inferred: { colour?: string; pattern?: string; material?: string } | null;
  inferenceConfidence: number | null;
  status: 'pending' | 'ready' | 'failed';
}

export class NotSignedIn extends Error {
  constructor() {
    super('Sign in to sync your wardrobe.');
    this.name = 'NotSignedIn';
  }
}

/** True when there is a usable token, so callers can skip the whole path. */
export async function canSync(): Promise<boolean> {
  return (await accessToken()) !== null;
}

/**
 * Content type from a file URI.
 *
 * The picker gives a path, not a MIME type, and the upload authorisation is
 * rejected for a type the server does not allow. Guessing from the extension
 * is sufficient because the server validates the bytes anyway.
 */
function contentTypeFor(uri: string): string {
  const extension = uri.split('?')[0].split('.').pop()?.toLowerCase();
  if (extension === 'png') return 'image/png';
  if (extension === 'webp') return 'image/webp';
  if (extension === 'heic' || extension === 'heif') return 'image/heic';
  return 'image/jpeg';
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
  const token = await accessToken();
  if (!token) throw new NotSignedIn();

  const response = await fetch(input.uri);
  const blob = await response.blob();
  const contentType = blob.type || contentTypeFor(input.uri);

  const authorized = await api.POST('/v1/uploads/authorize', {
    body: {
      kind: 'garment_photo',
      content_type: contentType,
      content_length: blob.size,
    },
  });
  if (authorized.error || !authorized.data) {
    throw new Error('Could not authorise the upload.');
  }
  const { asset_id, upload_url, required_headers } = authorized.data;

  // Sent with `fetch` rather than through the typed client: the destination
  // is a storage URL the server chose, not an endpoint in our own contract,
  // and in a deployment it is object storage that knows nothing about our
  // auth. The headers the authorisation hands back are passed through
  // unchanged for the same reason.
  const put = await fetch(upload_url, {
    method: 'PUT',
    headers: {
      ...(required_headers ?? {}),
      // Only the local development receiver needs this; a signed URL carries
      // its own authorisation in the query string and ignores it.
      ...(upload_url.startsWith(API_BASE_URL)
        ? { Authorization: `Bearer ${token}` }
        : {}),
    },
    body: blob,
  });
  if (!put.ok) {
    throw new Error(`The upload was rejected (${put.status}).`);
  }

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
export async function awaitProcessing(
  serverId: string,
  options: { attempts?: number; intervalMs?: number } = {},
): Promise<SyncedGarment> {
  const attempts = options.attempts ?? 20;
  const intervalMs = options.intervalMs ?? 1500;

  let last: SyncedGarment | null = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const read = await api.GET('/v1/wardrobe/garments/{garment_id}', {
      params: { path: { garment_id: serverId } },
    });
    if (read.error || !read.data) {
      throw new Error('Could not read the garment back.');
    }

    last = toSynced(serverId, read.data);
    // Categorisation is what decides the slot, so a category means the first
    // job has landed. The cut-out may still be in flight and is allowed to
    // arrive later; it changes the picture, not where the garment lives.
    if (last.status !== 'pending') return last;

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
    inferred: null,
    inferenceConfidence: null,
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
    // The server returns the cut-out as a delivered URL once it exists.
    cleanedUri: (data.background_removed_url as string | null) ?? null,
    inferred:
      colour || pattern || material ? { colour, pattern, material } : null,
    inferenceConfidence:
      typeof data.categorisation_confidence === 'number'
        ? data.categorisation_confidence
        : null,
    status: category ? 'ready' : 'pending',
  };
}
