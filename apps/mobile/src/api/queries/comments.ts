/**
 * Comments under a fit.
 *
 * **Not optimistic.** A comment is held until it has been screened, so
 * the state the server returns is the whole point: showing it as posted
 * and then correcting that a second later would be the app telling a
 * small lie and taking it back. The round trip is one request and the
 * row comes back with its real state.
 *
 * The count on a card is served with the card, so nothing here
 * recalculates it; writing or deleting invalidates the feed and the
 * card comes back correct.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const commentKeys = {
  of: (postId: string) => ['feed', 'comments', postId] as const,
};

export type CommentState = 'pending_review' | 'published' | 'held';

export interface Comment {
  id: string;
  authorId: string;
  authorName: string;
  body: string;
  /** `published`, or - for your own only - `pending_review` or `held`. */
  state: CommentState;
  /** Why it was held. Yours only; nobody else is told one exists. */
  note: string | null;
  parentId: string | null;
  /** True when you wrote it, which decides what you may do with it. */
  mine: boolean;
  createdAt: string | null;
  /** How many people liked it. Shown beside the heart from one up. */
  likes: number;
  /** Whether you are one of them, so the heart opens filled. */
  likedByMe: boolean;
}

export function useComments(postId: string, enabled: boolean) {
  return useQuery<Comment[]>({
    queryKey: commentKeys.of(postId),
    enabled: enabled && postId.length > 0,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/{post_id}/comments', {
        params: { path: { post_id: postId } },
      });
      return (data?.items ?? []).map((item) => ({
        id: String(item.id),
        authorId: String(item.author_id),
        authorName: item.author_name,
        body: item.body,
        state: item.state as CommentState,
        note: item.note ?? null,
        parentId: item.parent_id ? String(item.parent_id) : null,
        mine: Boolean(item.mine),
        createdAt: item.created_at ?? null,
        likes: item.likes ?? 0,
        likedByMe: Boolean(item.liked_by_me),
      }));
    },
  });
}

/** Thrown with the server's own words, so the screen can say them. */
export class CommentRefused extends Error {}

export function useWriteComment(postId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, parentId }: { body: string; parentId?: string }) => {
      const { data, error } = await api.POST('/v1/feed/{post_id}/comments', {
        params: { path: { post_id: postId } },
        body: { body, ...(parentId ? { parent_id: parentId } : {}) },
      });
      if (error || !data) {
        // The server's reason, not a generic one: "they are waiting to
        // be checked" is a different thing from "that fit is gone", and
        // only one of them means try again later.
        const detail = (error as { detail?: string } | undefined)?.detail;
        throw new CommentRefused(detail || 'That could not be posted.');
      }
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: commentKeys.of(postId) });
      void queries.invalidateQueries({ queryKey: ['feed'] });
    },
  });
}

export function useDeleteComment(postId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (commentId: string) => {
      await api.DELETE('/v1/feed/comments/{comment_id}', {
        params: { path: { comment_id: commentId } },
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: commentKeys.of(postId) });
      void queries.invalidateQueries({ queryKey: ['feed'] });
    },
  });
}

/**
 * Like a comment, or take it back.
 *
 * **Filled on the tap, corrected by the answer.** A heart that waits
 * for a round trip feels broken, so the row changes immediately and
 * the server's own tally replaces the guess when it lands. A failure
 * puts the old state back rather than leaving a heart that lies.
 */
export function useLikeComment(postId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, liked }: { id: string; liked: boolean }) => {
      // Written out rather than sharing one `options` object: the two
      // verbs infer their own response, and widening them to a common
      // type loses the tally this returns.
      const { data, error } = liked
        ? await api.PUT('/v1/feed/comments/{comment_id}/like', {
            params: { path: { comment_id: id } },
          })
        : await api.DELETE('/v1/feed/comments/{comment_id}/like', {
            params: { path: { comment_id: id } },
          });
      if (error || !data) throw new Error('That did not go through.');
      return data;
    },
    onMutate: async ({ id, liked }) => {
      await queries.cancelQueries({ queryKey: commentKeys.of(postId) });
      const before = queries.getQueryData<Comment[]>(commentKeys.of(postId));
      queries.setQueryData<Comment[]>(commentKeys.of(postId), (current) =>
        (current ?? []).map((comment) =>
          comment.id === id
            ? {
                ...comment,
                likedByMe: liked,
                likes: Math.max(0, comment.likes + (liked ? 1 : -1)),
              }
            : comment,
        ),
      );
      return { before };
    },
    onError: (_error, _variables, context) => {
      if (context?.before) {
        queries.setQueryData(commentKeys.of(postId), context.before);
      }
    },
    onSuccess: (data, { id }) => {
      // The server's count, not the one the tap guessed: two people
      // liking at once would otherwise leave the row one behind.
      queries.setQueryData<Comment[]>(commentKeys.of(postId), (current) =>
        (current ?? []).map((comment) =>
          comment.id === id
            ? { ...comment, likes: data.likes, likedByMe: data.liked_by_me }
            : comment,
        ),
      );
    },
  });
}
