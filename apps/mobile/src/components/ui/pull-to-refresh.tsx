import { useCallback, useState } from 'react';
import { RefreshControl } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import { Colors } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * Pull down, and the screen fetches again.
 *
 * **One control, used everywhere.** Three screens had their own and
 * six had none, so whether a drag did anything depended on which page
 * you were on - which is the kind of inconsistency people read as the
 * app being broken rather than as a missing feature.
 *
 * **It refetches what is on screen, not everything.** `refetchQueries`
 * with `type: 'active'` reaches the queries this screen is actually
 * subscribed to. Invalidating the whole cache would refetch the
 * wardrobe because somebody pulled on a tag page.
 *
 * **The spinner tracks the page, not the slowest thing on it.**
 * It used to await every active query at once, which meant it kept
 * turning long after the grid had repainted - the content was back,
 * visibly, and the wheel was still going because some counter or
 * shelf further down had not answered. A spinner that outlasts the
 * thing it describes reads as a hang.
 *
 * So a screen names its primary query, that one is awaited, and the
 * rest are refetched without being waited on. They still refresh;
 * they just do not hold the wheel. Given no primary, the old
 * behaviour stands, because for a simple screen "everything" and
 * "the page" are the same set.
 *
 * It is still tied to a promise rather than a timer: a spinner on a
 * timer is a screen claiming to be fresh on a guess.
 */
export function usePullToRefresh(
  extra?: () => Promise<unknown> | void,
  options?: {
    /**
     * The query this screen is actually about. The wheel stops when
     * this is back, whatever else is still in flight.
     */
    primary?: () => Promise<unknown>;
  },
) {
  const colors = Colors[useScheme()];
  const queries = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const primary = options?.primary;

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      if (primary) {
        // Everything on the screen is refreshed; only the primary
        // query is waited on. `void` rather than awaited, and the
        // rejection is swallowed deliberately - a shelf failing to
        // reload must not surface as the whole refresh failing, and
        // an unhandled rejection here would be a red box over a
        // page that refreshed fine.
        void Promise.allSettled([
          queries.refetchQueries({ type: 'active' }),
          Promise.resolve(extra?.()),
        ]);
        await primary();
      } else {
        await Promise.all([
          queries.refetchQueries({ type: 'active' }),
          extra?.() ?? Promise.resolve(),
        ]);
      }
    } finally {
      setRefreshing(false);
    }
  }, [queries, extra, primary]);

  return {
    refreshing,
    onRefresh,
    /** Spread onto any ScrollView, FlatList or FlashList. */
    control: (
      <RefreshControl
        refreshing={refreshing}
        onRefresh={() => void onRefresh()}
        // **Both platforms, and in the app's own colour.**
        //
        // `tintColor` is iOS-only: Android reads `colors`, so it was
        // drawing its stock blue wheel on a burgundy app, and a grey
        // one on iOS that was easy to miss against the page. The
        // accent is the colour this app uses for "something is
        // happening", which is exactly what this is.
        tintColor={colors.accent}
        colors={[colors.accent]}
        progressBackgroundColor={colors.background}
      />
    ),
  };
}
