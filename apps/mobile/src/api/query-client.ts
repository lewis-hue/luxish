import { QueryClient } from '@tanstack/react-query';

/**
 * One client for the app. `retry: 2` with exponential backoff rather than the
 * default, so a flaky mobile connection recovers without hammering the API; and
 * `staleTime` is non-zero because almost nothing here needs sub-minute freshness
 * (offers are the exception and set their own).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      staleTime: 60_000,
      // The app is frequently backgrounded mid-scroll; refetching on every focus
      // burns data for no benefit.
      refetchOnWindowFocus: false,
      // **Opening a screen always asks again.**
      //
      // The default is to ask only when the held answer is older than
      // `staleTime`, which means a screen opened twice inside a
      // minute shows the first answer and never checks. That is the
      // right trade for a list somebody is scrolling back through and
      // the wrong one for a page they navigated to on purpose: they
      // went there to see what is there now.
      //
      // Nothing is lost on the way. Whatever is cached paints
      // immediately and the request runs behind it, so this buys
      // freshness rather than a spinner. Queries that genuinely
      // cannot change - a treatment list, a vocabulary, an image
      // keyed by its own asset id - opt out with
      // `refetchOnMount: false` beside their `staleTime: Infinity`.
      refetchOnMount: 'always',
    },
  },
});

/**
 * Everything this account had cached, gone.
 *
 * **Signing out has to take the answers with it.** The tokens went,
 * the wardrobe went and the device registration went, but every
 * query result stayed in memory - so the next person to sign in on
 * the same phone opened a profile, a board or a thread and saw the
 * previous account's for as long as it took each request to come
 * back. Refetching on mount means it is replaced quickly; it does
 * not mean it was never shown.
 *
 * `clear` rather than `invalidateQueries`: invalidating marks data
 * stale and keeps it on screen while it refetches, which is exactly
 * the behaviour that is wrong here.
 */
export function forgetEverythingCached(): void {
  queryClient.clear();
}
