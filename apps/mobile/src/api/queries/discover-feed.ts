/**
 * Discover, built from what people here posted.
 *
 * **This replaced a catalogue.** The board used to be thirty-five
 * generated covers of invented people; it is now published fits by real
 * accounts, grouped by the hashtags their authors wrote. The taxonomy
 * covers still exist — they are the artwork a *look* is illustrated
 * with — but they are no longer what Discover shows.
 *
 * **A reaction is optimistic, a save is not.** Reacting is a cheap,
 * reversible thing somebody does while scrolling, and waiting a round
 * trip to colour the button in makes the whole board feel slow. Saving
 * writes to a library they will go looking in later, so that one waits
 * for the server and takes its count from the answer.
 */

import { useCallback, useRef } from 'react';
import {
  useMutation,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';

import { api } from '@/api/client';
import { mapItems, type PostItemTag } from '@/api/queries/posts';
import { rememberShape } from '@/features/feed/shapes';

export const feedKeys = {
  board: (group: string) => ['feed', 'board', group] as const,
  groups: ['feed', 'groups'] as const,
  saved: ['feed', 'saved'] as const,
  reactions: ['feed', 'reaction-kinds'] as const,
};

export interface FeedFit {
  id: string;
  authorId: string;
  /** First name only. The server never sends more than this. */
  authorName: string;
  /**
   * The author's own words, or - where they wrote none - what the clothes
   * in the photograph are. Never a replacement: a caption somebody typed
   * is always theirs.
   */
  caption: string | null;
  /** True when the caption above was read off the photograph. */
  captionIsDescribed: boolean;
  mediaAssetIds: string[];
  /**
   * The cover's width over its height, when the server knows it.
   *
   * Sent so a tile can be laid out before the bytes arrive. Null for
   * assets uploaded before dimensions were recorded; those are
   * measured on load instead.
   */
  coverRatio: number | null;
  /** What the author tagged it, normalised and without the `#`. */
  tags: string[];
  /** Which of the app's groups those tags put it in. Possibly none. */
  groups: string[];
  reactions: number;
  saves: number;
  /** Published comments this reader can see. */
  comments: number;
  /** This reader's own reaction, so the control shows its real state. */
  myReaction: string | null;
  savedByMe: boolean;
  publishedAt: string | null;
}

export interface FeedGroup {
  group: string;
  posts: number;
  /** Distinct people who reacted or saved. Not a count of presses. */
  people: number;
  trending: boolean;
}

export interface ReactionKind {
  kind: string;
  emoji: string;
}

/**
 * One fit, from the wire.
 *
 * Exported because a tag page returns the same shape from a different
 * endpoint, and two mappers for one shape is two places for a field to
 * be forgotten.
 */
export function toFeedFit(item: Record<string, unknown>): FeedFit {
  const fit: FeedFit = {
    id: String(item.id),
    authorId: String(item.author_id),
    authorName: String(item.author_name),
    coverRatio:
      typeof item.cover_ratio === 'number' ? item.cover_ratio : null,
    caption: (item.caption as string | null) ?? null,
    captionIsDescribed: Boolean(item.caption_is_described),
    mediaAssetIds: ((item.media_asset_ids as string[]) ?? []).map(String),
    tags: (item.tags as string[]) ?? [],
    groups: (item.groups as string[]) ?? [],
    reactions: Number(item.reactions ?? 0),
    saves: Number(item.saves ?? 0),
    comments: Number(item.comments ?? 0),
    myReaction: (item.my_reaction as string | null) ?? null,
    savedByMe: Boolean(item.saved_by_me),
    publishedAt: (item.published_at as string | null) ?? null,
  };
  // Every screen that shows a fit comes through here, so this is the one
  // place that can tell the *next* screen what shape the cover is before
  // its own request returns. See `features/feed/shapes`.
  rememberShape(fit.id, fit.coverRatio);
  return fit;
}

/** One page of the board, plus whether there is another. */
interface BoardPage {
  fits: FeedFit[];
  more: boolean;
}

export function useBoard(group: string, enabled: boolean) {
  const query = useInfiniteQuery<BoardPage>({
    queryKey: feedKeys.board(group),
    enabled,
    // **The page number is for the cache, not for the server.**
    //
    // There is no cursor and there does not need to be one: the
    // server records what it sent and excludes it next time, so
    // asking again walks forward on its own. A ranked offset would
    // be worse than useless, because the ranking is rebuilt per
    // request from a random walk - page two of a list that
    // reshuffled between requests is not page two of anything.
    // React Query still needs distinct page params to key them, so
    // this counts and is never sent.
    initialPageParam: 0,
    getNextPageParam: (last: BoardPage, pages: BoardPage[]) =>
      last.more ? pages.length : undefined,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed', {
        params: { query: group === 'all' ? {} : { group } },
      });
      return {
        fits: (data?.items ?? []).map((item) => toFeedFit(item as never)),
        // Absent on an older server, and false is the safe reading:
        // a board that stops paging is a short board, one that never
        // stops is an infinite loop.
        more: Boolean((data as { more?: boolean } | undefined)?.more),
      };
    },
    // **The grid is a session artifact, not a cached answer.**
    //
    // Every other query in this app opts into `refetchOnMount:
    // 'always'` because reopening a page should show what is there
    // now. This board is the exception, and asking again is actively
    // destructive here: the server picks a *different* grid each
    // time, records what it sent, and filters those pins out of the
    // next one. So a refetch does not refresh the board - it
    // replaces it, discards the scroll position, and burns through
    // the corpus.
    //
    // The symptom was precise: open a pin, tap back to Discover, and
    // the pins you were looking at are gone. A person returning from
    // something they tapped expects to find their place, and that is
    // what this preserves.
    //
    // The two things that *should* bring a new grid both stay: a
    // deliberate pull-down, and coming back to the app after leaving
    // it (`useReturnedToApp` on the screen).
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const client = useQueryClient();

  /**
   * Pull-to-refresh: one new page, not every page again.
   *
   * **An infinite query's own `refetch` re-fetches all of them**, in
   * order, so pulling down after scrolling twelve pages would fire
   * twelve recommender passes and take as long as the whole session
   * had. It also would not do what the gesture means: "show me
   * something new" is a request for a fresh board, not for the same
   * 360 pins re-picked.
   *
   * Dropping back to one page and fetching it is both faster and the
   * honest reading of the gesture. The server does the rest - it
   * remembers what it has sent, so the fresh page is genuinely new
   * rather than the same grid reshuffled.
   */
  const freshStart = useCallback(async () => {
    client.setQueryData(feedKeys.board(group), (held: unknown) => {
      const pages = held as { pages: BoardPage[]; pageParams: unknown[] } | undefined;
      if (!pages) return held;
      // Keep one page so the list has something to draw while the
      // new one arrives; replacing it with nothing blanks the board
      // mid-gesture.
      return { pages: pages.pages.slice(0, 1), pageParams: pages.pageParams.slice(0, 1) };
    });
    await query.refetch();
  }, [client, group, query]);

  // Flattened here so every caller keeps reading `data` as the list
  // of fits it always was, and only the screen that pages has to
  // know there are pages.
  return {
    ...query,
    data: query.data?.pages.flatMap((page: BoardPage) => page.fits),
    freshStart,
  };
}

export function useFeedGroups(enabled: boolean) {
  return useQuery<FeedGroup[]>({
    queryKey: feedKeys.groups,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/groups');
      return (data?.items ?? []).map((item) => ({
        group: String(item.group),
        posts: Number(item.posts ?? 0),
        people: Number(item.people ?? 0),
        trending: Boolean(item.trending),
      }));
    },
  });
}

/** The fits this person kept. Their library, and other people's posts. */
export function useSavedFits(enabled: boolean) {
  return useQuery<FeedFit[]>({
    queryKey: feedKeys.saved,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/saved');
      return (data?.items ?? []).map((item) => toFeedFit(item as never));
    },
  });
}

export interface FitAuthor {
  userId: string;
  name: string;
  handle: string | null;
  bio: string | null;
  followed: boolean;
  /**
   * Their own site, when they published one.
   *
   * Built by the server from a stored platform and handle, never from
   * a string somebody typed, so the Visit button can only ever go
   * where the profile field says it does.
   */
  website: string | null;
}

export interface FitDetail {
  fit: FeedFit;
  author: FitAuthor;
  /** What to look at next, from the groups this fit is in. */
  more: FeedFit[];
  /**
   * Where this fit lives, for sharing.
   *
   * Built by the server so the destination is decided in one place, and
   * empty when there is nowhere to point at - a caller then shares the
   * picture without a link rather than attaching a dead one.
   */
  link: string;
  /**
   * Whether the reader posted this.
   *
   * **From the server, not worked out here.** The app used to decide
   * by looking for the fit in the thirty newest of `/v1/posts/mine`,
   * so an author's thirty-first fit quietly lost the two controls
   * that are theirs alone.
   */
  mine: boolean;
  /** The author's own call on who this is for. Null for everybody else. */
  visibility: 'public' | 'private' | null;
  /**
   * The garments in this fit, each cut out of the photograph.
   *
   * The clothes themselves rather than a description of them, so
   * the stylised figure can wear the real thing. Empty until the
   * fit has been read, and empty for one nothing could be cut
   * from - the screen offers the photoreal render then, which is
   * what it did for everything before.
   */
  cutPieces: {
    mediaAssetId: string;
    position: number;
    name: string | null;
    colour: string | null;
    category: string | null;
  }[];
  /**
   * What the look is made of, for "Shop the look".
   *
   * Empty is the honest answer and the common one: nothing has been
   * tagged onto a fit yet. The menu reads the emptiness and says so
   * rather than offering a shelf that is not there.
   */
  items: PostItemTag[];
}

/**
 * One fit, its author, and what is like it.
 *
 * The whole detail screen in one request: three round trips to draw one
 * screen is three chances to show it half-built.
 */
/** The key the hook and the prefetch share, so they share a cache. */
export const fitDetailKey = (id: string) => ['feed', 'fit', id] as const;

/**
 * One fit and everything shown with it.
 *
 * A plain function rather than only a `queryFn`, so the same fetch
 * can be started from a tap on a tile - see `prefetchFitDetail`. Two
 * copies of this mapper would be two places for a field to be
 * forgotten.
 */
async function fetchFitDetail(id: string): Promise<FitDetail | null> {
  const { data } = await api.GET('/v1/feed/{post_id}', {
    params: { path: { post_id: id } },
  });
  if (!data) return null;
  const author = data.author as Record<string, unknown>;
  return {
    fit: toFeedFit(data.fit as never),
    author: {
      userId: String(author.user_id),
      name: String(author.name),
      handle: (author.handle as string | null) ?? null,
      bio: (author.bio as string | null) ?? null,
      followed: Boolean(author.followed),
      website: (author.website as string | null) ?? null,
    },
    more: (data.more ?? []).map((item) => toFeedFit(item as never)),
    link: (data.link as string | undefined) ?? '',
    cutPieces: ((data.pieces ?? []) as Record<string, unknown>[]).map(
      (piece) => ({
        mediaAssetId: String(piece.media_asset_id),
        position: Number(piece.position ?? 0),
        name: (piece.name as string | null) ?? null,
        colour: (piece.colour as string | null) ?? null,
        category: (piece.category as string | null) ?? null,
      }),
    ),
    items: mapItems(data.items as never),
    mine: Boolean(data.mine),
    visibility:
      data.visibility === 'public' || data.visibility === 'private'
        ? data.visibility
        : null,
  };
}

/**
 * Put what the tile already knows into the cache, now.
 *
 * **The picture is not what somebody is waiting for.** Tapping a pin
 * showed a full-page skeleton until a round trip came back, even
 * though the tile that was tapped already held the fit - its
 * photograph, its caption, its author's name - and the photograph
 * itself was already decoded and in cache. The screen had everything
 * it needed to draw the top half and was waiting anyway.
 *
 * Seeding makes the query resolve immediately with that much, so the
 * hero and the caption are there on arrival. The request started by
 * `prefetchFitDetail` is still in flight and replaces this the
 * moment it lands, filling in the author's handle, the related fits
 * and the share link - none of which is above the fold.
 *
 * The one thing this must not do is overwrite a real answer, so it
 * writes only into an empty slot.
 */

/**
 * Start fetching a fit before the screen that needs it exists.
 *
 * Called when a tile is tapped, not when the detail screen mounts.
 * A push, a mount and a first render all happen before a screen's
 * own `useQuery` fires, and on a slow network that is the difference
 * between the caption being there when the picture lands and
 * arriving a beat behind it.
 *
 * Deliberately quiet: this is work nobody asked for directly, so a
 * failure here is not an error anybody sees. The screen's own query
 * runs regardless and reports in its own words.
 */
export function seedFitDetail(queries: QueryClient, fit: FeedFit): void {
  const key = fitDetailKey(fit.id);
  // Never over real data. A second visit already holds the author,
  // the related fits and the link, and replacing those with a
  // placeholder would make going back worse than arriving.
  if (queries.getQueryData(key)) return;

  // Stale on arrival, deliberately. `setQueryData` stamps the data
  // as fetched now and the client holds things fresh for a minute,
  // so a seeded placeholder suppressed the request that was meant to
  // replace it - the author's own two controls, which depend on
  // `mine` coming back true, would not have appeared for a minute.
  queries.setQueryData<FitDetail>(key, {
    fit,
    author: {
      // The two the tile knows. The rest arrives with the request
      // that is already in flight.
      userId: fit.authorId,
      name: fit.authorName,
      handle: null,
      bio: null,
      followed: false,
      website: null,
    },
    more: [],
    link: '',
    // Not known from a tile, and deliberately seeded as not-yours.
    // The author's two controls appear a moment later when the real
    // response lands, which is the safe direction: briefly missing a
    // control somebody owns beats briefly offering one they do not.
    // A tile does not carry them, so the menu falls back to the
    // honest label until the real response lands.
    cutPieces: [],
    items: [],
    mine: false,
    visibility: null,
  }, { updatedAt: 0 });
}

export function prefetchFitDetail(queries: QueryClient, id: string): void {
  if (!id) return;
  void queries
    .prefetchQuery({
      queryKey: fitDetailKey(id),
      queryFn: () => fetchFitDetail(id),
      // Long enough to cover the push; the screen will not refetch
      // what it has just been handed.
      staleTime: 30_000,
    })
    .catch(() => {});
}

/**
 * "More to explore" under a pin, paged.
 *
 * **The shelf does not end, and neither does the next one.** Opening
 * a pin from this shelf opens a page with its own shelf, which pages
 * the same way - so somebody can go pin to pin to pin without ever
 * reaching a bottom. Before this, `more` was a fixed twelve computed
 * once with the detail, and the page simply stopped.
 *
 * What has already been shown is sent back with each request, held
 * in a ref rather than read back out of the query. Reading the
 * query's own pages inside its `queryFn` is a circular reference
 * that TypeScript rejects and that would be wrong anyway: the ref is
 * written as pages arrive, so the next request always sees the
 * current total rather than whatever React had rendered.
 *
 * It lives on the client because the shelf is per-pin and per-visit:
 * a server-side window spanning the session would make opening the
 * same pin twice show two different shelves, and the second would be
 * worse.
 */
export function useMoreUnder(id: string, enabled: boolean, seed: FeedFit[]) {
  // Only what this hook has fetched. The seed is folded in at
  // request time instead of being written here: a ref must not be
  // touched during render, and doing so would also mean the set
  // depended on how many times React happened to re-render.
  const fetched = useRef<Set<string>>(new Set());

  const query = useInfiniteQuery<BoardPage>({
    queryKey: ['feed', 'more', id],
    enabled: enabled && Boolean(id),
    initialPageParam: 0,
    getNextPageParam: (last: BoardPage, pages: BoardPage[]) =>
      last.more ? pages.length : undefined,
    queryFn: async (): Promise<BoardPage> => {
      const exclude = [
        ...new Set([...seed.map((fit) => fit.id), ...fetched.current]),
      ];
      const { data } = await api.GET('/v1/feed/{post_id}/more', {
        params: { path: { post_id: id }, query: { exclude } },
      });
      const fits = ((data?.items ?? []) as unknown[]).map((item) =>
        toFeedFit(item as never),
      );
      // Written here, inside the fetch, which is an event rather
      // than a render.
      for (const fit of fits) fetched.current.add(fit.id);
      return {
        fits,
        more: Boolean((data as { more?: boolean } | undefined)?.more),
      };
    },
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  return {
    ...query,
    extra: query.data?.pages.flatMap((page: BoardPage) => page.fits) ?? [],
  };
}

/** A garment cut out of a fit's photograph. */
export interface CutPiece {
  mediaAssetId: string;
  position: number;
  name: string | null;
  colour: string | null;
  category: string | null;
}

/**
 * Make sure a fit's garments are cut out, and watch them arrive.
 *
 * **This is the fast half of try-on.** Dressing a figure can be done
 * two ways. A photorealistic render describes the outfit to an image
 * model and pays it to draw somebody wearing that description -
 * fifteen to thirty seconds, billed every time, and what comes back
 * is clothes *like* the ones in the fit. Compositing lays each
 * garment, cut from the fit's own photograph, onto the mannequin:
 * the clothes are the actual clothes, it happens on the phone for
 * nothing, and it is instant.
 *
 * Compositing needs cut-outs. A pin nobody has opened has none, so
 * opening one starts the cut - a handful of segmentation calls,
 * once, after which every viewer of that pin gets it free. In
 * production most of this never runs: a garment is cut when it is
 * added to a wardrobe, so somebody trying on their own clothes
 * already has the pieces.
 *
 * Polls while the server says it is working and stops the moment the
 * pieces land, so an idle screen makes no requests.
 */
export function useCutOuts(id: string, enabled: boolean) {
  return useQuery<{ pieces: CutPiece[]; working: boolean }>({
    queryKey: ['feed', 'cut-outs', id],
    enabled: enabled && id.length > 0,
    // POST because it can start work, and safe to repeat - which is
    // exactly what polling does.
    queryFn: async () => {
      const { data } = await api.POST('/v1/feed/{post_id}/cut-outs', {
        params: { path: { post_id: id } },
      });
      const rows = (data?.pieces ?? []) as {
        media_asset_id: string;
        position: number;
        name: string | null;
        colour: string | null;
        category: string | null;
      }[];
      return {
        pieces: rows.map((row) => ({
          mediaAssetId: row.media_asset_id,
          position: row.position,
          name: row.name,
          colour: row.colour,
          category: row.category,
        })),
        working: Boolean((data as { working?: boolean } | undefined)?.working),
      };
    },
    // Four seconds: a cut is a handful of segmentation calls and
    // takes tens of seconds, so a tighter interval is requests
    // nobody reads.
    refetchInterval: (query) =>
      query.state.data?.working ? 4000 : false,
  });
}

export function useFitDetail(id: string, enabled: boolean) {
  return useQuery<FitDetail | null>({
    queryKey: fitDetailKey(id),
    enabled: enabled && id.length > 0,
    queryFn: () => fetchFitDetail(id),
  });
}

/**
 * Stop showing one fit on this person's board.
 *
 * Smaller than a block on purpose: not wanting one photograph again
 * is not the same as not wanting its author anywhere, and an app that
 * offers only the larger tool makes people reach for it.
 *
 * The board is invalidated rather than patched: a hidden fit should
 * leave every list it is in, and enumerating those here would be a
 * second copy of the server's own rule.
 */
export function useHideFit() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (postId: string) => {
      await api.PUT('/v1/feed/{post_id}/hide', {
        params: { path: { post_id: postId } },
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ['feed'] });
    },
  });
}

export function useReactionKinds(enabled: boolean) {
  return useQuery<ReactionKind[]>({
    queryKey: feedKeys.reactions,
    enabled,
    // A fixed set for the life of a release.
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    queryFn: async () => {
      const { data } = await api.GET('/v1/profiles/reactions');
      return (data?.items ?? []).map((item) => ({
        kind: String(item.kind),
        emoji: String(item.emoji),
      }));
    },
  });
}

/** Rewrite one fit everywhere it is currently on screen. */
function patchEverywhere(
  queries: ReturnType<typeof useQueryClient>,
  id: string,
  change: (fit: FeedFit) => FeedFit,
) {
  queries.setQueriesData<FeedFit[]>({ queryKey: ['feed'] }, (fits) =>
    Array.isArray(fits) ? fits.map((fit) => (fit.id === id ? change(fit) : fit)) : fits,
  );
  // The detail query holds a fit and a list of neighbours rather than a
  // plain array, so it needs its own pass — without this, reacting on
  // the detail screen left the number it was showing unchanged.
  queries.setQueriesData<FitDetail | null>({ queryKey: ['feed', 'fit'] }, (detail) =>
    detail && typeof detail === 'object' && 'fit' in detail
      ? {
          ...detail,
          fit: detail.fit.id === id ? change(detail.fit) : detail.fit,
          more: detail.more.map((fit) => (fit.id === id ? change(fit) : fit)),
        }
      : detail,
  );
}

export function useReact() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, kind }: { id: string; kind: string | null }) => {
      const { data, error } = await api.PUT('/v1/posts/{post_id}/reaction', {
        params: { path: { post_id: id } },
        body: { kind } as never,
      });
      if (error || !data) throw new Error('That fit is no longer there.');
      return { id, total: Number(data.total ?? 0), mine: data.mine ?? null };
    },
    onMutate: async ({ id, kind }) => {
      // Optimistic: reacting is cheap and reversible, and waiting a
      // round trip to colour the button in makes the board feel slow.
      await queries.cancelQueries({ queryKey: ['feed'] });
      patchEverywhere(queries, id, (fit) => {
        const had = fit.myReaction !== null;
        const has = kind !== null;
        return {
          ...fit,
          myReaction: kind,
          reactions: fit.reactions + (has ? 1 : 0) - (had ? 1 : 0),
        };
      });
    },
    onSuccess: (result) => {
      // The server's own count replaces the guess: other people have
      // been reacting too, and the guess only knew about this one.
      patchEverywhere(queries, result.id, (fit) => ({
        ...fit,
        reactions: result.total,
        myReaction: result.mine,
      }));
    },
    onError: () => {
      void queries.invalidateQueries({ queryKey: ['feed'] });
    },
  });
}

export function useSaveFit() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, saved }: { id: string; saved: boolean }) => {
      const path = '/v1/posts/{post_id}/save' as const;
      const options = { params: { path: { post_id: id } } };
      const { data, error } = saved
        ? await api.PUT(path, options as never)
        : await api.DELETE(path, options as never);
      if (error || !data) throw new Error('That fit is no longer there.');
      // `PUT` and `DELETE` declare separate response types, so the
      // union collapses to `never` on a shared variable even though
      // both return the same body.
      const body = data as { saves?: number; saved_by_me?: boolean };
      return { id, saves: Number(body.saves ?? 0), savedByMe: Boolean(body.saved_by_me) };
    },
    onSuccess: (result) => {
      // Not optimistic: a save writes to a library somebody will go
      // looking in, so the count is the server's rather than a guess.
      patchEverywhere(queries, result.id, (fit) => ({
        ...fit,
        saves: result.saves,
        savedByMe: result.savedByMe,
      }));
      void queries.invalidateQueries({ queryKey: feedKeys.saved });
    },
  });
}
