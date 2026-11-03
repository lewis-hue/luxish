/**
 * The garment studio: shots taken of a wardrobe item's own photograph.
 *
 * **A shot is requested, then polled.** The server answers 202 with a
 * queued row because an image edit is the better part of a minute of
 * billed work. Nothing here pretends otherwise — there is no optimistic
 * picture, because the only thing worse than waiting for a shot is being
 * shown one that is not the shot.
 *
 * Polling stops the moment nothing is in flight, so a screen left open on
 * a finished garment costs no requests.
 */

import { Directory, File, Paths } from 'expo-file-system';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

export const studioKeys = {
  /** Everything this person has shot, whatever it came from. */
  everything: ['garment-studio', 'shots'] as const,
  treatments: ['garment-studio', 'treatments'] as const,
  shots: (garmentId: string) => ['garment-studio', 'shots', garmentId] as const,
};

export type ShotState = 'queued' | 'running' | 'ready' | 'failed';

/** One thing the studio can do, described before it is paid for. */
export interface Treatment {
  id: string;
  label: string;
  description: string;
}

export interface Treatments {
  items: Treatment[];
  /** The one-source-image limitation, in the server's own words. */
  note: string;
}

export interface Shot {
  id: string;
  /** Null for a one-off photograph with no wardrobe item behind it. */
  garmentId: string | null;
  /** The photograph that was edited. Always present. */
  sourceAssetId: string;
  treatment: string;
  state: ShotState;
  /** Null until the edit comes back, and on a failure. */
  mediaAssetId: string | null;
  /** Why it failed. Null in every other state. */
  error: string | null;
  /** The direction it was asked for with, in the owner's own words. */
  brief: string | null;
  createdAt: string;
}

/** How often to ask while something is being taken. */
const POLL_MS = 3000;

export function useTreatments(enabled: boolean) {
  return useQuery<Treatments>({
    queryKey: studioKeys.treatments,
    enabled,
    // Static for the life of a release: it is a list of prompts.
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    queryFn: async () => {
      const { data } = await api.GET('/v1/garments/studio/treatments');
      return {
        items: (data?.items ?? []).map((item) => ({
          id: item.id,
          label: item.label,
          description: item.description,
        })),
        note: data?.note ?? '',
      };
    },
  });
}

function mapShot(item: Record<string, unknown>): Shot {
  return {
    id: String(item.id),
    // Nullable, and it used to be `String(item.garment_id)` - which
    // turned a one-off photograph's absent garment into the string
    // "null" and made every Studio shot look like it had one.
    garmentId: item.garment_id ? String(item.garment_id) : null,
    sourceAssetId: String(item.source_asset_id),
    treatment: String(item.treatment),
    state: item.state as ShotState,
    mediaAssetId: item.media_asset_id ? String(item.media_asset_id) : null,
    error: (item.error as string | null) ?? null,
    brief: (item.brief as string | null) ?? null,
    createdAt: String(item.created_at),
  };
}

export function useShots(garmentId: string, enabled: boolean) {
  return useQuery<Shot[]>({
    queryKey: studioKeys.shots(garmentId),
    enabled: enabled && garmentId.length > 0,
    // Only while something is actually being taken. A finished garment
    // polls at zero, which is the difference between a screen somebody
    // leaves open and a screen that keeps asking all afternoon.
    refetchInterval: (query) => {
      const shots = query.state.data ?? [];
      const working = shots.some(
        (shot) => shot.state === 'queued' || shot.state === 'running',
      );
      return working ? POLL_MS : false;
    },
    queryFn: async () => {
      const { data } = await api.GET('/v1/garments/{garment_id}/studio', {
        params: { path: { garment_id: garmentId } },
      });
      return (data?.items ?? []).map((item) => mapShot(item as never));
    },
  });
}

export function useRequestShot(garmentId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (treatment: string) => {
      const { data, error } = await api.POST('/v1/garments/{garment_id}/studio', {
        params: { path: { garment_id: garmentId } },
        body: { treatment } as never,
      });
      if (error || !data) {
        throw new Error('That did not start. Try again in a moment.');
      }
      return mapShot(data as never);
    },
    onSuccess: (shot) => {
      // Written straight in rather than invalidated, so the queued card
      // appears on the tap rather than a request later.
      queries.setQueryData<Shot[]>(studioKeys.shots(garmentId), (current) => {
        const rest = (current ?? []).filter((item) => item.id !== shot.id);
        return [shot, ...rest];
      });
    },
  });
}


/**
 * Everything this person has shot, newest first.
 *
 * The Studio tab's list. Unlike `useShots` this is not grouped by a
 * garment, because most of what lands here never was one - it is a
 * photograph somebody picked off their phone.
 */
export function useAllShots(enabled: boolean) {
  return useQuery<Shot[]>({
    queryKey: studioKeys.everything,
    enabled,
    // Only while something is actually being taken, same as the
    // per-garment list: a finished screen polls at zero.
    refetchInterval: (query) => {
      const shots = query.state.data ?? [];
      const working = shots.some(
        (shot) => shot.state === 'queued' || shot.state === 'running',
      );
      return working ? POLL_MS : false;
    },
    queryFn: async () => {
      const { data } = await api.GET('/v1/garments/studio/shots');
      return (data?.items ?? []).map((item) => mapShot(item as never));
    },
  });
}

/**
 * Shoot a photograph you own, with an optional direction of your own.
 *
 * The Studio tab's path: an asset id from the camera roll, a
 * treatment, and whatever somebody typed. The server places the
 * direction after the treatment's wording and before the clause
 * protecting the garment - that ordering is not this client's to
 * choose, which is why the brief is sent as plain text rather than
 * assembled here.
 */
export function useShootAsset() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (ask: {
      mediaAssetId: string;
      treatment: string;
      brief?: string;
      /**
       * Keep the wide frame a flat-lay comes back in.
       *
       * Everything this app draws sits in one upright shell, so the
       * server stands a flat-lay upright by default and this is the
       * opt-out. Sent per shot rather than remembered, because it is
       * a property of the picture being made.
       */
      landscape?: boolean;
    }) => {
      const { data, error } = await api.POST('/v1/garments/studio/shots', {
        body: {
          treatment: ask.treatment,
          media_asset_id: ask.mediaAssetId,
          brief: ask.brief?.trim() ? ask.brief.trim() : undefined,
          landscape: ask.landscape ?? false,
        } as never,
      });
      if (error || !data) {
        throw new Error('That did not start. Try again in a moment.');
      }
      return mapShot(data as never);
    },
    onSuccess: (shot) => {
      // Written straight in rather than invalidated, so the queued
      // card appears on the tap rather than a request later.
      queries.setQueryData<Shot[]>(studioKeys.everything, (current) => {
        const rest = (current ?? []).filter((item) => item.id !== shot.id);
        return [shot, ...rest];
      });
    },
  });
}

/**
 * One picture per garment in the photograph, instead of one of the lot.
 *
 * **The grouped shot stays the default.** Handed a photograph of a
 * shirt and trousers, the packshot treatment returns a single picture
 * with both laid out together, which is what somebody making an image
 * wants. This is the other case, asked for explicitly.
 *
 * Nothing useful comes back to show. How many pictures there will be
 * is however many garments a vision call finds, and that call runs on
 * a worker - so the shots arrive in the studio's own list as they are
 * made, which is the list somebody is already watching. The list is
 * invalidated rather than seeded for exactly that reason: there is no
 * card to write in yet.
 */
export function useShootEachItem() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (ask: {
      mediaAssetId: string;
      treatment: string;
      brief?: string;
      /** The same opt-out, carried per picture the split makes. */
      landscape?: boolean;
    }) => {
      const { data, error } = await api.POST('/v1/garments/studio/shots/each', {
        body: {
          treatment: ask.treatment,
          media_asset_id: ask.mediaAssetId,
          brief: ask.brief?.trim() ? ask.brief.trim() : undefined,
          landscape: ask.landscape ?? false,
        } as never,
      });
      if (error || !data) {
        throw new Error('That did not start. Try again in a moment.');
      }
      return String((data as { job_id: string }).job_id);
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: studioKeys.everything });
    },
  });
}

export function useDiscardShot(garmentId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (shotId: string) => {
      const { error } = await api.DELETE('/v1/garments/studio/shots/{shot_id}', {
        params: { path: { shot_id: shotId } },
      });
      if (error) throw new Error('Could not throw that away.');
      return shotId;
    },
    onSuccess: (shotId) => {
      queries.setQueryData<Shot[]>(studioKeys.shots(garmentId), (current) =>
        (current ?? []).filter((item) => item.id !== shotId),
      );
    },
  });
}

/** The line a shot shows about itself, in its owner's terms. */
export function shotLine(shot: Shot, treatments: readonly Treatment[]): string {
  const label = treatments.find((t) => t.id === shot.treatment)?.label ?? shot.treatment;
  if (shot.state === 'ready') return label;
  if (shot.state === 'queued') return `${label}, waiting`;
  if (shot.state === 'running') return `${label}, being taken`;
  return shot.error ?? `${label} did not come back`;
}

/* -------------------------------------------------------------------------- */
/* Fetching the pictures                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Studio shots are private media, so they are downloaded with the session
 * token rather than pointed at with a URL.
 *
 * Cached, because the file never changes: a shot is written once and then
 * only ever discarded. The cache directory rather than documents, because
 * every one of these is reproducible by paying for it again, and the OS
 * reclaiming it is the right trade against it counting toward the user's
 * storage forever.
 */
function studioDirectory(): Directory {
  const dir = new Directory(Paths.cache, 'garment-studio');
  if (!dir.exists) dir.create({ intermediates: true });
  return dir;
}

async function fetchShotImage(assetId: string): Promise<string | null> {
  const token = await accessToken();
  if (!token) return null;
  const target = new File(studioDirectory(), assetId);
  if (target.exists) return target.uri;
  try {
    const got = await File.downloadFileAsync(
      `${API_BASE_URL}/v1/uploads/local/${assetId}`,
      target,
      { headers: { Authorization: `Bearer ${token}` }, idempotent: true },
    );
    return got.uri;
  } catch (caught) {
    // A picture that failed to download is a missing image, not a reason
    // to fail the screen that was going to show it.
    if (__DEV__) console.warn('[studio] could not fetch', assetId, caught);
    return null;
  }
}

/**
 * Local file URIs for every ready shot, keyed by shot id.
 *
 * One query over the whole set rather than one per picture: a garment with
 * four shots would otherwise mount four queries that each re-run when any
 * of them settles.
 */
export function useShotImages(shots: readonly Shot[]) {
  const ready = shots
    .filter((shot) => shot.state === 'ready' && shot.mediaAssetId)
    .map((shot) => ({ id: shot.id, assetId: shot.mediaAssetId as string }));
  return useQuery<Record<string, string>>({
    queryKey: ['garment-studio', 'images', ready.map((r) => r.assetId).join(',')],
    enabled: ready.length > 0,
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    queryFn: async () => {
      const pairs = await Promise.all(
        ready.map(async (entry) => [entry.id, await fetchShotImage(entry.assetId)] as const),
      );
      return Object.fromEntries(
        pairs.filter((pair): pair is [string, string] => pair[1] !== null),
      );
    },
  });
}
