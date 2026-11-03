/**
 * The community tab's data.
 *
 * Three questions, each answered from something real rather than a fixture:
 * who else fell into your wardrobe cohort, what the people you follow have
 * kept, and how many people you follow. Trending lives in its own module
 * because Discover shows it too.
 *
 * **Nothing here can carry text another person wrote.** The server's shapes
 * have no field for it — see `app/schemas/community.py` — so there is no
 * free-text to render and no decision to get wrong at this layer.
 *
 * **The feed only contains people who agreed to be in it.** Following needs
 * no approval, so visibility is gated server-side on a `community_sharing`
 * consent. Nothing here has to enforce that, but it is why a feed can be
 * empty while you follow plenty of people, and the screen should not read
 * that as a failure.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';

import { api } from '@/api/client';

export const communityKeys = {
  follows: ['community', 'follows'] as const,
  people: (query: string) => ['community', 'people', query] as const,
  list: (direction: string) => ['community', 'list', direction] as const,
  memberList: (userId: string, direction: string) =>
    ['community', 'member-list', userId, direction] as const,
};

export function useFollowCounts(enabled: boolean) {
  return useQuery<{ following: number; followers: number }>({
    queryKey: communityKeys.follows,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/community/follows');
      return {
        following: data?.following ?? 0,
        followers: data?.followers ?? 0,
      };
    },
  });
}

/**
 * Follow or unfollow, with the button state flipped before the request.
 *
 * **Optimistic, and rolled back on failure.** A follow button that waits for
 * a round trip before changing reads as broken on a slow connection, and
 * people tap it again — which the server treats as idempotent but the person
 * experiences as "did that work?". The previous list is kept so a genuine
 * failure puts the button back rather than leaving a lie on screen.
 */
export function useSetFollowing() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ userId, follow }: { userId: string; follow: boolean }) => {
      const path = '/v1/community/follows/{user_id}' as const;
      const options = { params: { path: { user_id: userId } } };
      const { error } = follow
        ? await api.PUT(path, options as never)
        : await api.DELETE(path, options as never);
      if (error) throw new Error('That did not go through.');
    },
    onSettled: () => {
      // Both counts move with the follow graph.
      void queries.invalidateQueries({ queryKey: communityKeys.follows });
      // Every people search, whatever was typed into it, and both follow
      // lists: the follower count on a card is now wrong by one, and the
      // list this person is in has either gained or lost them.
      void queries.invalidateQueries({ queryKey: ['community', 'people'] });
      void queries.invalidateQueries({ queryKey: ['community', 'list'] });
      void queries.invalidateQueries({ queryKey: ['community', 'member-list'] });
    },
  });
}

/** Somebody found by name. */
export interface FoundPerson {
  userId: string;
  /** First name only, same as everywhere identity crosses. */
  name: string;
  followed: boolean;
  followerCount: number;
  /** Published fits. Also the reason they can be found at all. */
  fits: number;
}

/** A query shorter than this is not sent; the server answers it empty anyway. */
export const MIN_PEOPLE_QUERY = 2;

/**
 * Look somebody up by name.
 *
 * Only people who have published a fit are findable — the server decides
 * that, and the UI says so where the result is empty, because "no Marguerite
 * uses this app" and "Marguerite has never posted" are different answers and
 * the second one is the true one.
 */
export function usePeopleSearch(query: string, enabled: boolean) {
  const trimmed = query.trim();
  return useQuery<FoundPerson[]>({
    queryKey: communityKeys.people(trimmed),
    enabled: enabled && trimmed.length >= MIN_PEOPLE_QUERY,
    queryFn: async () => {
      const { data } = await api.GET('/v1/community/people', {
        params: { query: { q: trimmed } },
      });
      return (data?.items ?? []).map((item) => ({
        userId: String(item.user_id),
        name: item.name,
        followed: item.followed,
        followerCount: item.follower_count,
        fits: item.fits,
      }));
    },
  });
}

/**
 * The people who follow you, or the ones you follow.
 *
 * Yours only: a follower list is a list of real people, and the server
 * serves nobody else's. A member's page keeps its counts and stops
 * there.
 */
export function useFollowList(
  direction: 'followers' | 'following',
  enabled: boolean,
) {
  return useQuery<FoundPerson[]>({
    queryKey: communityKeys.list(direction),
    enabled,
    queryFn: async () => {
      const { data } = await api.GET(
        direction === 'followers'
          ? '/v1/community/followers'
          : '/v1/community/following',
      );
      return (data?.items ?? []).map((item) => ({
        userId: String(item.user_id),
        name: item.name,
        followed: item.followed,
        followerCount: item.follower_count,
        fits: item.fits,
      }));
    },
  });
}

/**
 * Somebody else's followers, or the people they follow.
 *
 * **Readable, unless they went private.** This app used to serve
 * nobody's list but your own, which meant the most ordinary question
 * about a person you just found - who else is here - had no answer.
 * The list is made of accounts that chose to be public, and the switch
 * for not wanting to be in one is the account itself being private.
 *
 * `private` comes back true with an empty list, so the screen can say
 * which it is: an empty list and a withheld one look the same and mean
 * opposite things.
 */
export interface FollowListPage {
  people: FoundPerson[];
  private: boolean;
}

export function useMemberFollowList(
  userId: string,
  direction: 'followers' | 'following',
  enabled: boolean,
) {
  return useQuery<FollowListPage>({
    queryKey: communityKeys.memberList(userId, direction),
    enabled: enabled && userId.length > 0,
    queryFn: async () => {
      const { data } = await api.GET(
        direction === 'followers'
          ? '/v1/community/members/{user_id}/followers'
          : '/v1/community/members/{user_id}/following',
        { params: { path: { user_id: userId } } },
      );
      return {
        people: (data?.items ?? []).map((item) => ({
          userId: String(item.user_id),
          name: item.name,
          followed: item.followed,
          followerCount: item.follower_count,
          fits: item.fits,
        })),
        private: Boolean(data?.private),
      };
    },
  });
}

/** One other person's page, as far as the server lets this viewer see. */
/** One tile on somebody's page: what to show, and what to open. */
export interface MemberFit {
  postId: string;
  /** Null when the fit has no readable photograph. */
  coverAssetId: string | null;
}

export interface Member {
  userId: string;
  name: string;
  /** What they chose to be called publicly, when they set one. */
  handle: string | null;
  /** The approved bio only. One in review does not cross. */
  bio: string | null;
  /** Platform to handle. The address is built at render time. */
  links: Record<string, string>;
  /** The picture across the top of their page, if the screen passed it. */
  bannerAssetId: string | null;
  followed: boolean;
  followsYou: boolean;
  followerCount: number;
  followingCount: number;
  /** Whether they let other people see what they keep. */
  shares: boolean;
  /** Fits they published, newest first, each with what to show. */
  posts: MemberFit[];
  /** How many in total, which is not how many came back. */
  postCount: number;
  /** Fits by other people they kept. Empty unless `shares`. */
  savedPosts: MemberFit[];
  /** This viewer blocked them. The other direction never reaches a client. */
  blocked: boolean;
  /**
   * They keep their fits and their two follow lists to themselves.
   *
   * The counts above are still true. A client says so rather than
   * drawing an empty grid, because an empty grid and a withheld one
   * look identical and mean opposite things.
   */
  private: boolean;
}

function toMemberFit(item: Record<string, unknown>): MemberFit {
  return {
    postId: String(item.post_id),
    coverAssetId: item.cover_asset_id ? String(item.cover_asset_id) : null,
  };
}

/** The key the hook and the seed share, so they share a cache. */
export const memberKey = (userId: string) =>
  ['community', 'member', userId] as const;

/**
 * Put the little that is already known about somebody into the cache.
 *
 * **The same waiting problem as a pin, on a bigger page.** Opening a
 * profile showed a whole-page skeleton until a round trip returned,
 * even though whatever was tapped to get there - a fit, a comment, a
 * follower row - already carried this person's id and name. The
 * header could have been drawn immediately and was not.
 *
 * What is seeded is only what the caller genuinely knows. Counts are
 * zero and the posts list is empty until the real answer lands, and
 * both arrive together rather than ticking up - a count that starts
 * at zero and jumps is worse than a count that appears.
 *
 * Never over a real answer: a second visit already holds everything,
 * and replacing it with a stub would make going back worse than
 * arriving.
 */
export function seedMember(
  queries: QueryClient,
  known: { userId: string; name: string },
): void {
  const key = memberKey(known.userId);
  if (queries.getQueryData(key)) return;

  // **Stamped as already stale, which is the whole point.**
  //
  // `setQueryData` records the data as fetched *now*, and the client
  // holds things fresh for a minute - so a placeholder seeded this
  // way told every query that asked for sixty seconds that it
  // already had the answer. The screen opened instantly on a profile
  // with no posts, no followers and nobody's bio, and stayed that
  // way until somebody pulled to refresh. `prefetchMember` running
  // immediately after was skipped for the same reason.
  //
  // `updatedAt: 0` keeps the instant paint and marks it stale, so
  // the real request goes out on mount and replaces this the moment
  // it lands.
  queries.setQueryData<Member>(key, {
    userId: known.userId,
    name: known.name,
    followed: false,
    followsYou: false,
    followerCount: 0,
    // Whether they share a shelf of other people's looks, not a count.
    shares: false,
    handle: null,
    bio: null,
    links: {},
    bannerAssetId: null,
    followingCount: 0,
    posts: [],
    postCount: 0,
    savedPosts: [],
    blocked: false,
    private: false,
  }, { updatedAt: 0 });
}

/**
 * Start fetching a profile before the screen that needs it exists.
 *
 * Quiet on every path: this is work nobody asked for directly, and
 * the screen's own query reports in its own words.
 */
export function prefetchMember(queries: QueryClient, userId: string): void {
  if (!userId) return;
  void queries
    .prefetchQuery({
      queryKey: memberKey(userId),
      queryFn: () => fetchMember(userId),
      staleTime: 30_000,
    })
    .catch(() => {});
}

async function fetchMember(userId: string): Promise<Member> {
  const { data, error } = await api.GET('/v1/community/members/{user_id}', {
    params: { path: { user_id: userId } },
  });
  if (error || !data) throw new Error('No such account.');
  return {
    userId: String(data.user_id),
    name: data.name,
    followed: data.followed,
    followsYou: data.follows_you,
    followerCount: data.follower_count,
    shares: data.shares,
    handle: data.handle ?? null,
    bio: data.bio ?? null,
    links: (data.links ?? {}) as Record<string, string>,
    bannerAssetId: data.banner_asset_id ? String(data.banner_asset_id) : null,
    followingCount: data.following_count ?? 0,
    posts: (data.posts ?? []).map(toMemberFit),
    postCount: data.post_count ?? 0,
    savedPosts: (data.saved_posts ?? []).map(toMemberFit),
    blocked: data.blocked,
    private: Boolean(data.private),
  };
}

export function useMember(userId: string, enabled: boolean) {
  return useQuery<Member>({
    queryKey: memberKey(userId),
    enabled,
    queryFn: () => fetchMember(userId),
  });
}

/**
 * Block or unblock. Blocking severs follows both ways on the server, so
 * everything derived from the graph is invalidated together.
 */
export function useSetBlocked() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ userId, blocked }: { userId: string; blocked: boolean }) => {
      const path = '/v1/community/blocks/{user_id}' as const;
      const options = { params: { path: { user_id: userId } } };
      const { error } = blocked
        ? await api.PUT(path, options as never)
        : await api.DELETE(path, options as never);
      if (error) throw new Error('That did not go through.');
    },
    onSettled: (_data, _error, { userId }) => {
      void queries.invalidateQueries({ queryKey: ['community', 'member', userId] });
      void queries.invalidateQueries({ queryKey: communityKeys.follows });
      void queries.invalidateQueries({ queryKey: ['community', 'list'] });
      void queries.invalidateQueries({ queryKey: ['community', 'member-list'] });
    },
  });
}

export type ReportReason = 'impersonation' | 'inappropriate' | 'spam' | 'other';

/** File a report. It is recorded for a person to read; nothing automated
 *  acts on it, and the UI must not imply otherwise. */
export function useReport() {
  return useMutation({
    mutationFn: async (input: {
      subjectKind: 'account' | 'look';
      subjectUserId?: string;
      reason: ReportReason;
      note?: string;
    }) => {
      const { error } = await api.POST('/v1/community/reports', {
        body: {
          subject_kind: input.subjectKind,
          subject_user_id: input.subjectUserId,
          reason: input.reason,
          note: input.note,
        } as never,
      });
      if (error) throw new Error('The report did not go through.');
    },
  });
}
