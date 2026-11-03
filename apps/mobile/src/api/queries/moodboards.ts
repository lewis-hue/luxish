/**
 * Moodboards: named boards, and what is pinned to them.
 *
 * Distinct from saving, and the distinction is the point. Saving is
 * "I like this"; pinning is "this belongs with these others". One is a
 * verdict on a single fit, the other an argument about several.
 *
 * Every mutation returns the whole board, so the list stays correct without a
 * second round trip and a pin never renders before the server has agreed to
 * it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const moodboardKeys = { all: ['moodboards'] as const };

export interface Moodboard {
  id: string;
  name: string;
  note: string | null;
  /** The fits on the board, in the order they were arranged. */
  postIds: readonly string[];
  /**
   * The same fits, each with the picture to show for it.
   *
   * Pairs rather than ids: a tile needs the asset to render and the
   * post to open. Without this the board screen had post pins it
   * could not draw, which is why pinning a fit appeared to do
   * nothing.
   */
  posts: readonly { postId: string; coverAssetId: string | null }[];
}

export function useMoodboards(enabled: boolean) {
  return useQuery<Moodboard[]>({
    queryKey: moodboardKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/moodboards');
      return (data?.items ?? []).map((item) => ({
        id: item.id,
        name: item.name,
        note: item.note ?? null,
        postIds: item.post_ids ?? [],
        posts: (item.posts ?? []).map((pinned) => ({
          postId: String(pinned.post_id),
          coverAssetId: pinned.cover_asset_id
            ? String(pinned.cover_asset_id)
            : null,
        })),
      }));
    },
  });
}

/**
 * Any board mutation, with the list refreshed after it.
 *
 * Generic over the result as well as the input, so `useCreateBoard` can hand
 * back the board it made — pinning straight onto a board somebody just named
 * is the common case, and it needs the id.
 */
function useBoardMutation<T, R>(run: (input: T) => Promise<R>) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: moodboardKeys.all });
    },
  });
}

export function useCreateBoard() {
  return useBoardMutation(async ({ name, note }: { name: string; note?: string }) => {
    const { data } = await api.POST('/v1/moodboards', {
      body: note === undefined ? { name } : { name, note },
    });
    return data;
  });
}

export function useRenameBoard() {
  return useBoardMutation(
    async ({ id, name, note }: { id: string; name?: string; note?: string }) => {
      await api.PATCH('/v1/moodboards/{board_id}', {
        params: { path: { board_id: id } },
        // Only what is being changed. Omitting a field means "not talking
        // about it", which is what keeps a rename from blanking a note.
        body: {
          ...(name === undefined ? {} : { name }),
          ...(note === undefined ? {} : { note }),
        },
      });
    },
  );
}

export function useDeleteBoard() {
  return useBoardMutation(async (id: string) => {
    await api.DELETE('/v1/moodboards/{board_id}', {
      params: { path: { board_id: id } },
    });
  });
}

/** Put somebody else's fit on a board. */
export function usePinPost() {
  return useBoardMutation(async ({ id, postId }: { id: string; postId: string }) => {
    await api.PUT('/v1/moodboards/{board_id}/posts/{post_id}', {
      params: { path: { board_id: id, post_id: postId } },
    });
  });
}

export function useUnpinPost() {
  return useBoardMutation(async ({ id, postId }: { id: string; postId: string }) => {
    await api.DELETE('/v1/moodboards/{board_id}/posts/{post_id}', {
      params: { path: { board_id: id, post_id: postId } },
    });
  });
}

/**
 * Which boards a published fit is already on.
 *
 * Computed here rather than asked for, because the whole collection comes
 * back with every board and a second endpoint for a question already
 * answerable from data in hand is one more thing to keep in step.
 */
export function boardsHoldingPost(
  boards: readonly Moodboard[] | undefined,
  postId: string,
): Set<string> {
  return new Set(
    (boards ?? []).filter((board) => board.postIds.includes(postId)).map((b) => b.id),
  );
}
