/**
 * A seeded placeholder must never suppress the request it stands in for.
 *
 * **The bug this guards.** Tapping somebody in search or on a fit
 * writes what the tile already knows straight into the cache, so the
 * profile paints instantly instead of showing a skeleton. But
 * `setQueryData` stamps its data as fetched *now*, and this app holds
 * query results fresh for a minute - so for sixty seconds every query
 * that asked was told the answer was already in hand. The profile
 * opened on nobody: no posts, no followers, no bio, `private: false`,
 * and it stayed that way until the person pulled down to refresh. The
 * `prefetch` call running immediately afterwards was skipped for
 * exactly the same reason, so nothing was in flight either.
 *
 * The seeds therefore stamp `updatedAt: 0`. The paint is still
 * instant; the data is stale from the moment it is written, so the
 * real request goes out on mount and replaces it.
 */
import { QueryClient } from '@tanstack/react-query';

import { queryClient } from '@/api/query-client';

import { memberKey, seedMember } from '@/api/queries/community';
import { fitDetailKey, seedFitDetail } from '@/api/queries/discover-feed';
import type { FeedFit } from '@/api/queries/discover-feed';

/** The app's own stale window, which is what made the seeds stick. */
const FRESH_FOR = 60_000;

/**
 * Whether a mounting screen would refetch this.
 *
 * `isStale()` is the wrong question and answers `false` here: with no
 * observer attached it reports on the query as it sits, not on what a
 * component asking for it would get. `isStaleByTime` is what an
 * observer consults on mount, and is the thing the fix has to move.
 */
function wouldRefetch(queries: QueryClient, key: readonly unknown[]): boolean {
  const found = queries.getQueryCache().find({ queryKey: key });
  return Boolean(found?.isStaleByTime(FRESH_FOR));
}

/** The real client's policy, which is what made the seeds stick. */
function client() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: FRESH_FOR, retry: false } },
  });
}

const FIT = {
  id: 'fit-1',
  authorId: 'u1',
  authorName: 'Imani',
  caption: 'Linen',
  mediaAssetIds: ['asset-1'],
  coverRatio: 0.75,
} as unknown as FeedFit;

describe('seedMember', () => {
  it('paints at once', () => {
    const queries = client();
    seedMember(queries, { userId: 'u1', name: 'Imani' });
    expect(queries.getQueryData(memberKey('u1'))).toBeDefined();
  });

  it('is stale the moment it is written', () => {
    // Not a detail. Fresh placeholder data is indistinguishable to
    // React Query from a real answer, and the screen keeps it.
    const queries = client();
    seedMember(queries, { userId: 'u1', name: 'Imani' });
    expect(wouldRefetch(queries, memberKey('u1'))).toBe(true);
  });

  it('would not have refetched before the fix', () => {
    // The same seed written the way it used to be, so the test says
    // what actually changed rather than only what is true now.
    const queries = client();
    queries.setQueryData(memberKey('u2'), { userId: 'u2', name: 'Imani' });
    expect(wouldRefetch(queries, memberKey('u2'))).toBe(false);
  });

  it('does not stop a prefetch from running', () => {
    // The pair is seed-then-prefetch. A fresh seed made the prefetch
    // a no-op, so nothing was in flight behind the placeholder.
    const queries = client();
    seedMember(queries, { userId: 'u1', name: 'Imani' });

    let asked = 0;
    void queries.prefetchQuery({
      queryKey: memberKey('u1'),
      queryFn: async () => {
        asked += 1;
        return { userId: 'u1', name: 'Imani' };
      },
      staleTime: 30_000,
    });
    expect(asked).toBe(1);
  });

  it('never writes over real data already held', () => {
    // A second visit holds the whole profile. Replacing it with a
    // placeholder would make going back worse than arriving.
    const queries = client();
    queries.setQueryData(memberKey('u1'), { userId: 'u1', name: 'Real', posts: [1] });
    seedMember(queries, { userId: 'u1', name: 'Placeholder' });
    expect(
      (queries.getQueryData(memberKey('u1')) as { name: string }).name,
    ).toBe('Real');
  });
});

describe('seedFitDetail', () => {
  it('is stale the moment it is written', () => {
    // This one carries `mine: false`, because a tile cannot know
    // whose fit it is. Left fresh, an author opening their own pin
    // would wait a minute for "Make it private" and "Delete this
    // fit" to appear.
    const queries = client();
    seedFitDetail(queries, FIT);
    expect(wouldRefetch(queries, fitDetailKey('fit-1'))).toBe(true);
  });

  it('still paints the top half at once', () => {
    const queries = client();
    seedFitDetail(queries, FIT);
    const held = queries.getQueryData(fitDetailKey('fit-1')) as {
      fit: { id: string };
      author: { name: string };
    };
    expect(held.fit.id).toBe('fit-1');
    expect(held.author.name).toBe('Imani');
  });

  it('never writes over real data already held', () => {
    const queries = client();
    queries.setQueryData(fitDetailKey('fit-1'), { fit: FIT, mine: true, link: 'real' });
    seedFitDetail(queries, FIT);
    expect(
      (queries.getQueryData(fitDetailKey('fit-1')) as { mine: boolean }).mine,
    ).toBe(true);
  });
});

describe('opening a screen asks again', () => {
  // The other half of the same complaint. Even with the seeds fixed,
  // the default was to ask only when the held answer was older than
  // a minute - so a page opened twice inside one showed the first
  // answer and never checked. Someone who navigates to a profile
  // went there to see what is there now.
  it('refetches on mount even when the held answer is fresh', async () => {
    const queries = new QueryClient({
      defaultOptions: {
        queries: { staleTime: FRESH_FOR, retry: false, refetchOnMount: 'always' },
      },
    });
    queries.setQueryData(memberKey('u3'), { userId: 'u3', name: 'Held' });

    let asked = 0;
    await queries.fetchQuery({
      queryKey: memberKey('u3'),
      queryFn: async () => {
        asked += 1;
        return { userId: 'u3', name: 'Fresh' };
      },
      staleTime: 0,
    });
    expect(asked).toBe(1);
  });

  it('is what the app actually sets', () => {
    // A default nobody applied is a default that does nothing, and
    // this one is easy to drop in a merge. Asserted against the real
    // client's resolved options rather than its source text: an
    // earlier version grepped the file it used to live in, and went
    // on passing after it moved.
    expect(queryClient.getDefaultOptions().queries?.refetchOnMount).toBe(
      'always',
    );
  });
});
