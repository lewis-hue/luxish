/**
 * The avatar, and putting outfits on it.
 *
 * **Drawing happens on a worker and is polled.** A generate measured at 27
 * seconds and a try-on at 15 to 21; asking for one returns a *render* — a row
 * with a state — and this file watches it until it is ready or failed. The
 * screen never waits on a request, so no dropped connection can strand a
 * spinner over work that is actually still running.
 *
 * The picture is fetched to a file on the device rather than rendered from a
 * URL, for the same reason garment cut-outs are: the delivery endpoint needs
 * a bearer token, and a token in an `Image` header is a token that expires
 * behind a cached picture.
 *
 * Nothing here runs on its own. Both calls are billed, so each happens
 * because somebody tapped.
 */

import { Directory, File, Paths } from 'expo-file-system';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

export const avatarKeys = {
  current: ['avatar'] as const,
  renders: ['avatar', 'renders'] as const,
};

/** What someone said about how they look. Asked, never inferred. */
export interface Appearance {
  presentation: 'feminine' | 'masculine' | 'androgynous' | 'unspecified';
  bodyType: 'slim' | 'average' | 'athletic' | 'curvy' | 'plus' | 'unspecified';
  /**
   * Bands rather than a measurement. A number would be a measurement of a
   * person held on a server, and the prompt can only act on the difference
   * anyway: an image model draws "tall", not 174cm.
   */
  height: 'tall' | 'average' | 'short' | 'unspecified';
  ageBand: '20s' | '30s' | '40s' | '50s' | '60s_plus' | 'unspecified';
  skinTone:
    | 'very_fair'
    | 'fair'
    | 'medium'
    | 'olive'
    | 'brown'
    | 'dark_brown'
    | 'deep'
    | 'unspecified';
}

export const EMPTY_APPEARANCE: Appearance = {
  presentation: 'unspecified',
  bodyType: 'unspecified',
  height: 'unspecified',
  ageBand: 'unspecified',
  skinTone: 'unspecified',
};

/** One garment in a picture, as it was asked for. */
export interface Piece {
  name: string;
  colour: string | null;
  category: string | null;
}

export type RenderState = 'queued' | 'running' | 'ready' | 'failed';

export interface Render {
  id: string;
  kind: 'base' | 'try_on';
  state: RenderState;
  assetId: string | null;
  outfit: string | null;
  /** Labelled and searchable, without a second model call. */
  pieces: readonly Piece[];
  error: string | null;
  /** Local file URI, once the picture has been fetched. */
  uri: string | null;
}

export interface Avatar {
  assetId: string | null;
  /** Local file URI for the picture, once it has been fetched. */
  uri: string | null;
  appearance: Appearance;
  /**
   * Whether this person asked to be shown as a photorealistic
   * likeness instead of the mannequin.
   *
   * False for everybody who has not said otherwise, new or old. The
   * mannequin is the default everywhere, and having generated a
   * likeness once does not change that.
   */
  onMyAvatar: boolean;
}

/** True while a render is still being drawn. */
export function isWorking(state: RenderState | undefined): boolean {
  return state === 'queued' || state === 'running';
}

/**
 * Where a fetched picture lands.
 *
 * The avatar goes in `document`: it is the user's, expensive to draw, and
 * losing it means paying again. A try-on goes in `cache`, where the system
 * may reclaim it, because it is a derived preview that costs one edit to
 * reproduce — and because every try-on writes a new file.
 */
function directory(ephemeral: boolean): Directory {
  const dir = new Directory(ephemeral ? Paths.cache : Paths.document, 'avatar');
  if (!dir.exists) dir.create({ intermediates: true });
  return dir;
}

/**
 * Pull one picture down and return a file URI for it.
 *
 * Returns null rather than throwing: a picture that failed to download is a
 * missing image, not a reason to fail the screen that was going to show it.
 */
async function fetchAvatarImage(
  assetId: string,
  { ephemeral = false }: { ephemeral?: boolean } = {},
): Promise<string | null> {
  const token = await accessToken();
  if (!token) return null;
  const target = new File(directory(ephemeral), assetId);
  if (target.exists) return target.uri;
  try {
    const got = await File.downloadFileAsync(
      `${API_BASE_URL}/v1/uploads/local/${assetId}`,
      target,
      { headers: { Authorization: `Bearer ${token}` }, idempotent: true },
    );
    return got.uri;
  } catch (caught) {
    if (__DEV__) console.warn('[avatar] could not fetch', assetId, caught);
    return null;
  }
}

function readAppearance(raw: Record<string, unknown> | undefined): Appearance {
  return {
    presentation: (raw?.presentation ?? 'unspecified') as Appearance['presentation'],
    bodyType: (raw?.body_type ?? 'unspecified') as Appearance['bodyType'],
    height: (raw?.height ?? 'unspecified') as Appearance['height'],
    ageBand: (raw?.age_band ?? 'unspecified') as Appearance['ageBand'],
    skinTone: (raw?.skin_tone ?? 'unspecified') as Appearance['skinTone'],
  };
}

export function useAvatar(enabled: boolean) {
  return useQuery<Avatar>({
    queryKey: avatarKeys.current,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/avatar');
      const assetId = data?.asset_id ?? null;
      return {
        assetId,
        uri: assetId ? await fetchAvatarImage(assetId) : null,
        appearance: readAppearance(data?.appearance as Record<string, unknown>),
        onMyAvatar: Boolean(
          (data as { on_my_avatar?: boolean } | undefined)?.on_my_avatar,
        ),
      };
    },
  });
}

/**
 * Switch between the mannequin and a photorealistic likeness.
 *
 * Separate from generating one, deliberately. Drawing a likeness and
 * choosing to be shown as one are two decisions, and before they were
 * separated the first silently made the second with no way back.
 */
export function useChooseVehicle() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (onMyAvatar: boolean) => {
      await api.PUT('/v1/avatar/vehicle', {
        body: { on_my_avatar: onMyAvatar } as never,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: avatarKeys.current });
    },
  });
}

/**
 * Every render this person asked for, polled while any is still drawing.
 *
 * The interval stops once nothing is in flight, so an idle screen makes no
 * requests at all. Three seconds because a draw takes fifteen to twenty-seven
 * — polling faster buys nothing and costs a request every second of it.
 */
export function useRenders(enabled: boolean) {
  return useQuery<Render[]>({
    queryKey: avatarKeys.renders,
    enabled,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((render) => isWorking(render.state)) ? 3000 : false,
    queryFn: async () => {
      const { data } = await api.GET('/v1/avatar/renders');
      const items = data?.items ?? [];
      return Promise.all(
        items.map(async (item) => ({
          id: item.id,
          kind: item.kind as Render['kind'],
          state: item.state as RenderState,
          assetId: item.asset_id ?? null,
          outfit: item.outfit ?? null,
          pieces: (item.pieces ?? []).map((piece) => ({
            name: piece.name,
            colour: piece.colour ?? null,
            category: piece.category ?? null,
          })),
          error: item.error ?? null,
          // Only a finished picture is worth a download.
          uri: item.asset_id
            ? await fetchAvatarImage(item.asset_id, {
                ephemeral: item.kind === 'try_on',
              })
            : null,
        })),
      );
    },
  });
}

/**
 * Record how somebody says they look.
 *
 * Does not redraw. Changing a detail and spending a billed call on a new
 * picture are two decisions, and answering a question should not trigger the
 * second one.
 */
export function useSetAppearance() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (next: Appearance) => {
      const { data } = await api.PUT('/v1/avatar/appearance', {
        body: {
          presentation: next.presentation,
          body_type: next.bodyType,
          height: next.height,
          age_band: next.ageBand,
          skin_tone: next.skinTone,
        },
      });
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: avatarKeys.current });
    },
  });
}

/** Ask for the base figure to be drawn. Returns at once; poll the render. */
export function useCreateAvatar() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.POST('/v1/avatar');
      return data?.id ?? null;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: avatarKeys.renders });
    },
  });
}

/**
 * Ask for an outfit to be put on the avatar.
 *
 * The pieces travel with the request and are stored as asked for, so the
 * finished picture can be labelled and each garment searched without paying
 * a vision model to tell us what we just requested.
 */
export function useTryOn() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({
      outfit,
      pieces,
    }: {
      outfit: string;
      pieces?: readonly {
        name: string;
        colour: string | null;
        category?: string | null;
      }[];
    }) => {
      const { data } = await api.POST('/v1/avatar/try-on', {
        body: {
          outfit,
          pieces: (pieces ?? []).slice(0, 8).map((piece) => ({
            name: piece.name,
            colour: piece.colour,
            category: piece.category ?? null,
          })),
        },
      });
      return data?.id ?? null;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: avatarKeys.renders });
    },
  });
}

/**
 * Put the outfit in somebody's published fit on your own avatar.
 *
 * A different call from {@link useTryOn} because the input is different:
 * there is no outfit sentence to send. The server reads the clothes out
 * of the photograph - once, storing the result so the next person to try
 * the same fit skips it - and draws them on this person's avatar. Both
 * halves run on a worker, so this answers at once with a render to poll.
 *
 * 404 when the fit has been withdrawn or its author is blocked either
 * way, which is the same answer as never having existed.
 */
export function useTryOnFit() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (postId: string) => {
      const { data, error } = await api.POST('/v1/feed/{post_id}/try-on', {
        params: { path: { post_id: postId } },
      });
      if (error || !data) {
        throw new Error('That fit cannot be tried on right now.');
      }
      return data.render_id;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: avatarKeys.renders });
    },
  });
}

/**
 * A look, as a sentence the image model can dress someone in.
 *
 * Built from the pieces rather than the title, because "Gorpcore" is a name
 * and "a weatherproof shell jacket over a zip fleece" is an instruction. The
 * colour leads each piece for the same reason it leads in the prompt that
 * drew the avatar.
 */
export function outfitSentence(
  pieces: readonly { name: string; colour: string | null }[],
): string {
  const described = pieces
    .map((piece) =>
      piece.colour && !piece.name.toLowerCase().includes(piece.colour.toLowerCase())
        ? `${piece.colour} ${piece.name.toLowerCase()}`
        : piece.name.toLowerCase(),
    )
    .slice(0, 6);
  return described.join(', ');
}

/**
 * Stop a picture that is being drawn.
 *
 * **There was no way to do this, and that was the whole of the stale-render
 * problem.** One render is allowed in flight per kind, so while a row said it
 * was working, asking again returned that row instead of drawing. A render
 * whose worker had died held the progress card open and the feature shut for
 * the ten minutes it took the server's sweep to reclaim it. Someone who had
 * simply picked the wrong garment had the same wait.
 *
 * Cancelling finishes the row, which frees the next request, so there is no
 * retry mutation to pair with this: retrying is `useCreateAvatar` or
 * `useTryOn` again. Both lists are invalidated because the avatar screen
 * reads `current` and the progress card reads `renders`, and a stop that
 * leaves either one saying "drawing" has not visibly worked.
 */
export function useCancelRender() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (renderId: string) => {
      const { data } = await api.POST('/v1/avatar/renders/{render_id}/cancel', {
        params: { path: { render_id: renderId } },
      });
      return data ?? null;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: avatarKeys.renders });
      void queries.invalidateQueries({ queryKey: avatarKeys.current });
    },
  });
}
