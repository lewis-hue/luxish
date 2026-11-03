/**
 * Photographs attached to posts.
 *
 * **Private media, so it is downloaded with the session token rather
 * than pointed at with a URL.** The same approach the avatar uses: the
 * bytes come down once, into the cache directory, and `expo-image`
 * renders a local file from then on.
 *
 * **One query per asset, and a bounded number of downloads.** A board
 * is a hundred and twenty fits. Keying by the asset means a tile seen
 * once resolves from cache rather than refetching; capping how many
 * download at once means the ones on screen arrive first instead of
 * every tile competing for the same connection.
 */

import { Directory, File, Paths } from 'expo-file-system';
import { useQuery } from '@tanstack/react-query';

import { API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

/**
 * How many pictures may be downloading at once, across every tile.
 *
 * Six because that is what the batch hook settled on: a phone's
 * connection is the bottleneck, and a hundred and twenty parallel
 * downloads make the first row arrive later than six at a time would.
 */
const AT_ONCE = 6;

let active = 0;
const waiting: (() => void)[] = [];

/**
 * Run `work` once there is a slot, newest caller first.
 *
 * **Newest, not oldest.** Scrolling leaves a trail of requests for tiles
 * that have since gone off screen; in arrival order the picture somebody
 * is actually looking at queues behind every one they scrolled past.
 *
 * The slot passes straight from the finishing caller to the next waiter
 * rather than being released and re-taken, so the count cannot drift
 * above the cap in the gap between the two.
 *
 * Exported for its test: the cap and the order are the behaviour worth
 * pinning, and they are testable without a filesystem in the way.
 */
export async function queued<T>(work: () => Promise<T>): Promise<T> {
  if (active >= AT_ONCE) {
    await new Promise<void>((go) => waiting.push(go));
  } else {
    active += 1;
  }
  try {
    return await work();
  } finally {
    const next = waiting.pop();
    if (next) next();
    else active -= 1;
  }
}

/** How many are downloading and queued. For tests. */
export function downloadLoad(): { active: number; waiting: number } {
  return { active, waiting: waiting.length };
}

function directory(): Directory {
  const dir = new Directory(Paths.cache, 'post-media');
  if (!dir.exists) dir.create({ intermediates: true });
  return dir;
}

async function fetchOne(assetId: string): Promise<string | null> {
  const token = await accessToken();
  if (!token) return null;
  const target = new File(directory(), assetId);
  // Checked before queueing: a picture already on disk is not a download
  // and must not wait behind six that are.
  if (target.exists) return target.uri;
  try {
    const got = await queued(() =>
      File.downloadFileAsync(
        `${API_BASE_URL}/v1/uploads/local/${assetId}`,
        target,
        { headers: { Authorization: `Bearer ${token}` }, idempotent: true },
      ),
    );
    return got.uri;
  } catch (caught) {
    // A picture that failed to download is a missing image, not a
    // reason to fail the board that was going to show it.
    if (__DEV__) console.warn('[post-media] could not fetch', assetId, caught);
    return null;
  }
}

/**
 * One picture, by asset id.
 *
 * **The key is the asset, not the request.** A board of a hundred and
 * twenty tiles calling the batch hook with its own one-element array
 * gave every tile its own cache entry, so scrolling back up refetched
 * pictures already on disk and every recycled cell mounted a fresh
 * query. Keyed by the asset, a tile that has been seen once resolves
 * from cache on the spot - which is what the board scrolling smoothly
 * depends on.
 *
 * The bytes never change: an id addresses one immutable file, so this
 * never goes stale and never refetches.
 */
export function usePostImage(assetId: string | null | undefined) {
  const id = assetId ?? '';
  return useQuery<string | null>({
    queryKey: ['post-media', 'one', id],
    enabled: id.length > 0,
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    gcTime: Infinity,
    queryFn: () => fetchOne(id),
  });
}

/**
 * Local file URIs for a set of assets, keyed by asset id.
 *
 * For a screen that knows every picture it needs up front. A list
 * whose cells come and go should use `usePostImage` instead: one
 * entry per asset shares between cells, where one entry per request
 * cannot.
 *
 * Downloads run in parallel but bounded: a board's worth of images all
 * at once saturates a phone connection and makes the first row arrive
 * later than it would have one at a time.
 */
export function usePostImages(assetIds: readonly string[]) {
  const wanted = [...new Set(assetIds)].filter(Boolean);
  return useQuery<Record<string, string>>({
    queryKey: ['post-media', wanted.join(',')],
    enabled: wanted.length > 0,
    // The bytes never change: an asset id addresses one immutable file.
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    queryFn: async () => {
      const out: Record<string, string> = {};
      const BATCH = 6;
      for (let at = 0; at < wanted.length; at += BATCH) {
        const slice = wanted.slice(at, at + BATCH);
        const pairs = await Promise.all(
          slice.map(async (id) => [id, await fetchOne(id)] as const),
        );
        for (const [id, uri] of pairs) {
          if (uri) out[id] = uri;
        }
      }
      return out;
    },
  });
}
