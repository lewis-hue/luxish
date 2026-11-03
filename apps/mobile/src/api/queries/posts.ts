/**
 * Fits: the community's user-authored feed.
 *
 * A created fit answers `pending_review` and the UI says so: nothing is
 * optimistic about publication, because the server's screen is the thing
 * that publishes, and a card shown as live before the screen agreed
 * would be the lie the whole pipeline exists to prevent.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const postKeys = {
  feed: ['posts', 'feed'] as const,
  mine: ['posts', 'mine'] as const,
};

export interface PostItemTag {
  kind: 'garment' | 'product' | 'gone';
  categoryId: string | null;
  colour: string | null;
  title: string | null;
  brand: string | null;
  retailer: string | null;
  priceMinor: number | null;
  currency: string | null;
  sourceUrl: string | null;
}

export interface FeedPost {
  id: string;
  authorId: string;
  authorName: string;
  caption: string | null;
  occasion: string | null;
  mediaAssetIds: string[];
  items: PostItemTag[];
  publishedAt: string | null;
  /** How many people kept this fit. */
  saves: number;
  /** Whether you are one of them. */
  savedByMe: boolean;
}

export interface MinePost extends FeedPost {
  state: 'pending_review' | 'published' | 'held' | 'removed';
  /**
   * Who the author meant it for, which is theirs and separate from
   * `state`. A held fit that is public is still held; a private fit
   * the screen cleared is still private.
   */
  visibility: 'public' | 'private';
  /**
   * The cover's width over its height, when the server knows it. The
   * profile's masonry lays a tile out from this before any bytes
   * arrive, which is what stops the column re-flowing as they land.
   */
  coverRatio: number | null;
  screenMode: string | null;
  screenNote: string | null;
  createdAt: string;
}

export function mapItems(
  items: readonly Record<string, unknown>[] | undefined,
): PostItemTag[] {
  return (items ?? []).map((item) => ({
    kind: item.kind as PostItemTag['kind'],
    categoryId: (item.category_id as string | null) ?? null,
    colour: (item.colour as string | null) ?? null,
    title: (item.title as string | null) ?? null,
    brand: (item.brand as string | null) ?? null,
    retailer: (item.retailer as string | null) ?? null,
    priceMinor: (item.price_minor as number | null) ?? null,
    currency: (item.currency as string | null) ?? null,
    sourceUrl: (item.source_url as string | null) ?? null,
  }));
}

export function usePostFeed(enabled: boolean) {
  return useQuery<FeedPost[]>({
    queryKey: postKeys.feed,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/posts/feed');
      return (data?.items ?? []).map((item) => ({
        id: String(item.id),
        authorId: String(item.author_id),
        authorName: item.author_name,
        caption: item.caption ?? null,
        occasion: item.occasion ?? null,
        mediaAssetIds: (item.media_asset_ids ?? []).map(String),
        items: mapItems(item.items as never),
        publishedAt: item.published_at ?? null,
        saves: item.saves ?? 0,
        savedByMe: item.saved_by_me ?? false,
      }));
    },
  });
}

export function useMyPosts(enabled: boolean) {
  return useQuery<MinePost[]>({
    queryKey: postKeys.mine,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/posts/mine');
      return (data?.items ?? []).map((item) => ({
        id: String(item.id),
        authorId: String(item.author_id),
        authorName: item.author_name,
        caption: item.caption ?? null,
        occasion: item.occasion ?? null,
        mediaAssetIds: (item.media_asset_ids ?? []).map(String),
        items: mapItems(item.items as never),
        publishedAt: item.published_at ?? null,
        saves: item.saves ?? 0,
        savedByMe: item.saved_by_me ?? false,
        state: item.state,
        visibility: item.visibility ?? 'public',
        coverRatio: item.cover_ratio ?? null,
        screenMode: item.screen_mode ?? null,
        screenNote: item.screen_note ?? null,
        createdAt: item.created_at,
      }));
    },
  });
}

export function useCreatePost() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      caption?: string;
      occasion?: string;
      /** Photographs already uploaded from this phone. */
      mediaAssetIds?: string[];
      garmentIds?: string[];
    }) => {
      const { data, error } = await api.POST('/v1/posts', {
        body: {
          caption: input.caption,
          occasion: input.occasion,
          media_asset_ids: input.mediaAssetIds ?? [],
          garment_ids: input.garmentIds ?? [],
        } as never,
      });
      if (error || !data) throw new Error('The fit did not go through.');
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: postKeys.mine });
    },
  });
}

export function useDeletePost() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (postId: string) => {
      const { error } = await api.DELETE('/v1/posts/{post_id}', {
        params: { path: { post_id: postId } },
      });
      if (error) throw new Error('Could not take it down.');
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: postKeys.mine });
      void queries.invalidateQueries({ queryKey: postKeys.feed });
    },
  });
}

/**
 * Show a fit to people, or stop.
 *
 * **Not a smaller delete.** A private fit is still the author's, still
 * on their own profile and still theirs to put back - somebody who
 * only wanted it off the board should not have to destroy it.
 *
 * The new setting is written into the cached list from the server's
 * answer rather than guessed, so a refusal leaves the switch where it
 * actually is instead of where the tap hoped it would be.
 */
export function useSetPostVisibility() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (next: { postId: string; visibility: 'public' | 'private' }) => {
      const { data, error } = await api.PUT('/v1/posts/{post_id}/visibility', {
        params: { path: { post_id: next.postId } },
        body: { visibility: next.visibility },
      });
      if (error || !data) throw new Error('Could not change who can see it.');
      return data;
    },
    onSuccess: (data) => {
      queries.setQueryData<MinePost[]>(postKeys.mine, (held) =>
        (held ?? []).map((post) =>
          post.id === String(data.id)
            ? { ...post, visibility: data.visibility }
            : post,
        ),
      );
      // Everybody else's board changes too, so it is no longer right.
      void queries.invalidateQueries({ queryKey: postKeys.feed });
    },
  });
}

/**
 * Keep or forget a fit.
 *
 * The count is written straight into both caches from the server's answer
 * rather than incremented locally: two people keeping the same fit at once
 * would otherwise each see their own count, and the number on a picture is
 * the one claim on the card that is checkable.
 */
export function useSavePost() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (input: { postId: string; saved: boolean }) => {
      const request = input.saved ? api.PUT : api.DELETE;
      const { data, error } = await request('/v1/posts/{post_id}/save', {
        params: { path: { post_id: input.postId } },
      });
      if (error || !data) throw new Error('That fit is no longer there.');
      return { postId: input.postId, saves: data.saves, savedByMe: data.saved_by_me };
    },
    onSuccess: (result) => {
      const apply = (posts: FeedPost[] | undefined) =>
        posts?.map((post) =>
          post.id === result.postId
            ? { ...post, saves: result.saves, savedByMe: result.savedByMe }
            : post,
        );
      queries.setQueryData<FeedPost[]>(postKeys.feed, apply);
      queries.setQueryData<MinePost[]>(postKeys.mine, apply as never);
    },
  });
}

/** The state line the author sees on their own fit. */
export function stateLine(post: Pick<MinePost, 'state' | 'screenNote'>): string {
  if (post.state === 'published') return 'Published.';
  if (post.state === 'pending_review') {
    return 'In review. It appears to others once the screen approves it.';
  }
  if (post.state === 'held') return post.screenNote ?? 'Held for review.';
  return 'Removed.';
}
