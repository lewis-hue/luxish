import { FlashList } from '@shopify/flash-list';
import { router } from 'expo-router';
import { View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSavedFits } from '@/api/queries/discover-feed';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { SkeletonMasonry } from '@/components/ui/skeleton';
import {
  BottomTabInset,
  Colors,
  FontSize,
  Spacing,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { FitCard } from '@/features/feed/fit-card';
import { useScheme } from '@/hooks/use-theme';

/**
 * Everything you kept.
 *
 * **Fits, not catalogue entries.** This was the shelf of curated
 * looks from the generated catalogue, while the Save button on every
 * photograph in the app wrote somewhere else entirely — so the
 * screen named after that button did not contain anything it had
 * saved. It now reads the same thing the button writes.
 *
 * Bare tiles, like every other board here: these are pictures you
 * already chose, and a row of controls under each one is a decision
 * nobody is taking on this screen.
 */
export default function SavedScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const { width, height } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const saved = useSavedFits(signedIn);

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.two;
  const column = (width - Spacing.three * 2 - gutter * (columns - 1)) / columns;
  const fits = saved.data ?? [];

  if (!signedIn) {
    return (
      <EmptyState
        status="blocked"
        title="Sign in to see what you kept"
        body="Keeping a fit is part of an account."
        action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
      />
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <FlashList
        data={fits}
        masonry
        drawDistance={height}
        keyExtractor={(item) => item.id}
        numColumns={columns}
        refreshControl={refresh.control}
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          paddingHorizontal: Spacing.three - gutter / 2,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        }}
        showsVerticalScrollIndicator={false}
        ListHeaderComponent={
          <View
            style={{
              paddingHorizontal: gutter / 2,
              paddingTop: Spacing.three,
              paddingBottom: Spacing.three,
              gap: Spacing.half,
            }}>
            <ThemedText
              accessibilityRole="header"
              style={{ ...labelType(28, 800), lineHeight: 34 }}>
              Saved
            </ThemedText>
            {fits.length > 0 ? (
              <ThemedText
                themeColor="textSecondary"
                style={labelType(FontSize.subhead, 400)}>
                {fits.length === 1 ? '1 fit' : `${fits.length} fits`}
              </ThemedText>
            ) : null}
          </View>
        }
        renderItem={({ item }) => (
          <View style={{ paddingHorizontal: gutter / 2, paddingBottom: gutter }}>
            <FitCard
              fit={item}
              width={column}
              onOpen={() =>
                router.push({ pathname: '/fit/[id]', params: { id: item.id } })
              }
            />
          </View>
        )}
        ListEmptyComponent={
          saved.isPending ? (
            <View style={{ paddingHorizontal: gutter / 2 }}>
              <SkeletonMasonry
                count={6}
                columns={columns}
                gutter={gutter}
                label="Loading what you kept"
              />
            </View>
          ) : (
            <EmptyState
              status="empty"
              title="Nothing kept yet"
              body="Tap Save on a fit and it lands here."
              action={{
                label: 'Find some',
                onPress: () => router.replace('/'),
              }}
            />
          )
        }
      />
    </View>
  );
}
