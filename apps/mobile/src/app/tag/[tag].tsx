import { FlashList } from '@shopify/flash-list';
import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { ScrollView, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTagFeed } from '@/api/queries/tags';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { SkeletonMasonry } from '@/components/ui/skeleton';
import {
  BottomTabInset,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { FitCard } from '@/features/feed/fit-card';
import { useScheme } from '@/hooks/use-theme';

/**
 * One hashtag, and everything under it.
 *
 * **A search, not a slice of the board.** The board shows what is
 * around; tapping a tag is somebody saying what they want. So this is
 * its own request with no recency window and no reordering by stated
 * taste: ranking a person's own search by their profile would be
 * overruling them.
 *
 * **Related tags sit at the top, not the bottom.** A tag that turns out
 * to be broader than what was wanted is a dead end otherwise, and the
 * moment somebody realises it is while they are looking at the first
 * screenful rather than after scrolling a hundred fits.
 */
export default function TagScreen() {
  const { tag } = useLocalSearchParams<{ tag: string }>();
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const page = useTagFeed(tag ?? '', signedIn);
  const refresh = usePullToRefresh();
  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.three;
  const column = (width - gutter * (columns + 1)) / columns;

  if (!signedIn) {
    return (
      <EmptyState
        status="blocked"
        title="Sign in to browse"
        body="Fits are posted by people with accounts, and seeing them needs one."
        action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
      />
    );
  }

  /**
   * One row, then one line of chips, then photographs.
   *
   * It was a 32-point serif title, a count and three rows of chips,
   * which put the first photograph most of a screen down a page whose
   * whole job is photographs. The tag still names the page - it sits
   * in the field where the reference puts the query.
   */
  /**
   * The way back and what was searched, pinned above the grid.
   *
   * Out of the list on purpose: in `ListHeaderComponent` it scrolled
   * away with the first row of photographs, so getting out of a tag
   * meant scrolling back to the top first.
   */
  const bar = (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
        paddingTop: insets.top + Spacing.two,
        paddingHorizontal: gutter,
        paddingBottom: Spacing.two,
        backgroundColor: colors.background,
      }}>
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel="Back"
        animateEntrance={false}
        scale={0.9}
        hitSlop={10}
        onPress={() => {
          void tapFeedback();
          // `back` when there is history, which is every normal
          // arrival. A cold start on a tag link has nothing behind
          // it, so that lands on Discover rather than a dead end.
          if (router.canGoBack()) router.back();
          else router.replace('/');
        }}
        style={{
          width: TapTarget,
          height: TapTarget,
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        <SymbolView
          name={{ ios: 'chevron.left', android: 'arrow_back', web: 'arrow_back' }}
          size={20}
          tintColor={colors.text}
        />
      </MotionPressable>

      {/* The tag, in the field the reference puts the query in. It
          reads as "this is what you searched", which is what a tag
          page is. */}
      <View
        accessible
        accessibilityRole="header"
        style={{
          flex: 1,
          minHeight: TapTarget,
          justifyContent: 'center',
          paddingHorizontal: Spacing.three,
          borderRadius: Radius.full,
          borderWidth: 1,
          borderColor: colors.border,
        }}>
        <ThemedText numberOfLines={1} style={labelType(FontSize.body, 400)}>
          #{page.data?.tag ?? tag}
        </ThemedText>
      </View>
    </View>
  );

  /** Related tags. These may scroll away; the way back may not. */
  const header =
    (page.data?.related ?? []).length > 0 ? (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{
          gap: Spacing.two,
          paddingRight: Spacing.three,
          paddingBottom: Spacing.two,
        }}>
        {page.data?.related.map((other) => (
          <MotionPressable
            key={other}
            accessibilityRole="link"
            accessibilityLabel={`Fits tagged ${other}`}
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              // `push`, not `replace`: wandering from tag to tag is
              // browsing, and the way back out is the way you came.
              router.push({ pathname: '/tag/[tag]', params: { tag: other } });
            }}
            style={{
              minHeight: 36,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.full,
              backgroundColor: colors.backgroundElement,
            }}>
            <ThemedText style={labelType(FontSize.subhead, 400)}>
              #{other}
            </ThemedText>
          </MotionPressable>
        ))}
      </ScrollView>
    ) : null;

  if (page.isPending) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          gap: Spacing.two,
        }}>
        {bar}
        <View style={{ paddingHorizontal: gutter }}>{header}</View>
        {/* The same shape the grid will be, so nothing moves when the
            fits land. Two hand-placed blocks were a different shape
            from the masonry that replaced them. */}
        <SkeletonMasonry
          count={6}
          columns={columns}
          gutter={gutter}
          label={`Loading fits tagged ${tag}`}
        />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {bar}
      <FlashList
        // A screen and a half of pre-render rather than the default
        // quarter-screen. On a board of photographs the cells that
        // have not been rendered yet are the blank boxes that flick
        // past during a fast scroll, and they are what reads as the
        // list glitching.
        drawDistance={height}
        data={page.data?.fits ?? []}
        refreshControl={refresh.control}
        keyExtractor={(fit) => fit.id}
        numColumns={columns}
        masonry
        // No `contentInsetAdjustmentBehavior`: it asks iOS to inset
        // the scroll view by the safe area, and the padding below
        // already does that. With both, the inset was counted twice
        // and recalculated as the list scrolled, which is what moved
        // the content under the finger.
        contentContainerStyle={{
          paddingTop: Spacing.one,
          paddingHorizontal: gutter,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        }}
        ListHeaderComponent={header}
        ListEmptyComponent={
          <EmptyState
            status="empty"
            title="Nothing under this one yet"
            body="Tag a fit with it when you post, and it will show up here."
          />
        }
        renderItem={({ item }) => (
          <View style={{ paddingBottom: Spacing.three, paddingRight: gutter }}>
            <FitCard
              fit={item}
              width={column}
              onOpen={() =>
                router.push({ pathname: '/fit/[id]', params: { id: item.id } })
              }
            />
          </View>
        )}
      />
    </View>
  );
}
