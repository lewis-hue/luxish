import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { StyleTile } from '@/components/ui/style-tile';
import {
  BottomTabInset,
  Colors,
  Display,
  FontSize,
  Radius,
  Spacing,
} from '@/constants/theme';
import { STYLE_CATEGORIES, type StyleCategory } from '@/features/discover/collections';
import { coverFor } from '@/features/discover/imagery';
import { useScheme } from '@/hooks/use-theme';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'casual', label: 'Casual' },
  { id: 'smart_casual', label: 'Smart casual' },
  { id: 'business', label: 'Office' },
  { id: 'formal', label: 'Formal' },
  { id: 'black_tie', label: 'Evening' },
] as const;

type FilterId = (typeof FILTERS)[number]['id'];

/**
 * Discover — style tiles, curated inspiration and search entry (§3).
 *
 * Composed as one lead tile over a two-column grid rather than a uniform grid.
 * A uniform grid of twelve equal tiles has no entry point: the eye has nowhere to
 * land first, and every category reads as equally (un)important. The lead tile gives
 * the screen a first beat, and the grid below it carries the breadth.
 *
 * Virtualised throughout (§17), with the header and lead tile as the list header so
 * they scroll with the content and cost nothing extra to render.
 */
export default function DiscoverScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [filter, setFilter] = useState<FilterId>('all');

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.two;

  const visible = useMemo(
    () =>
      filter === 'all'
        ? STYLE_CATEGORIES
        : STYLE_CATEGORIES.filter((category) => category.formality === filter),
    [filter],
  );

  // The lead tile is the first match, so it changes with the filter rather than
  // being pinned to one category that the filter may have excluded.
  const [lead, ...rest] = visible;

  return (
    <FlatList
      style={{ backgroundColor: colors.background }}
      data={rest}
      keyExtractor={(item) => item.id}
      numColumns={columns}
      key={columns}
      columnWrapperStyle={columns > 1 ? { gap: gutter } : undefined}
      contentContainerStyle={{
        paddingTop: insets.top + Spacing.three,
        paddingHorizontal: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        gap: gutter,
      }}
      windowSize={5}
      initialNumToRender={6}
      removeClippedSubviews
      showsVerticalScrollIndicator={false}
      ListHeaderComponent={
        <Header
          filter={filter}
          onFilter={setFilter}
          count={visible.length}
          lead={lead}
          gutter={gutter}
        />
      }
      renderItem={({ item, index }) => <Tile category={item} index={index} />}
      ListEmptyComponent={
        lead ? undefined : (
          <View style={{ paddingVertical: Spacing.six, alignItems: 'center' }}>
            <ThemedText type="small" themeColor="textSecondary">
              Nothing in this category yet.
            </ThemedText>
          </View>
        )
      }
    />
  );
}

function Tile({ category, index }: { category: StyleCategory; index: number }) {
  return (
    <StyleTile
      index={index}
      style={{ flex: 1 }}
      asset={coverFor(category.id, category.subtitle ?? category.title)}
      title={category.title}
      subtitle={null}
      meta={category.cues[0] ?? null}
      onPress={() => router.push({ pathname: '/look/[id]', params: { id: category.id } })}
    />
  );
}

function Header({
  filter,
  onFilter,
  count,
  lead,
  gutter,
}: {
  filter: FilterId;
  onFilter: (id: FilterId) => void;
  count: number;
  lead: StyleCategory | undefined;
  gutter: number;
}) {
  const colors = Colors[useScheme()];

  return (
    <View style={{ gap: Spacing.three, marginBottom: gutter }}>
      <View style={{ gap: Spacing.half }}>
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: 11, letterSpacing: 1.4, textTransform: 'uppercase' }}>
          {count} {count === 1 ? 'collection' : 'collections'}
        </ThemedText>
        <ThemedText
          style={{
            fontFamily: Display.regular,
            fontSize: 44,
            lineHeight: 46,
            letterSpacing: -0.5,
            color: colors.text,
          }}>
          Discover
        </ThemedText>
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
        {FILTERS.map((option) => {
          const active = option.id === filter;
          return (
            <Pressable
              key={option.id}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onFilter(option.id)}
              hitSlop={6}
              style={({ pressed }) => ({
                minHeight: 34,
                justifyContent: 'center',
                paddingHorizontal: Spacing.three,
                borderRadius: Radius.full,
                backgroundColor: active ? colors.text : 'transparent',
                borderWidth: 1,
                // The inactive border matches the surface, so only the active chip
                // draws a hard edge and the row stays quiet.
                borderColor: active ? colors.text : colors.border,
                opacity: pressed ? 0.6 : 1,
              })}>
              <ThemedText
                type="small"
                style={{
                  fontSize: FontSize.footnote,
                  color: active ? colors.background : colors.textSecondary,
                }}>
                {option.label}
              </ThemedText>
            </Pressable>
          );
        })}
      </View>

      {lead ? (
        <StyleTile
          feature
          asset={coverFor(lead.id, lead.subtitle ?? lead.title)}
          title={lead.title}
          subtitle={lead.subtitle}
          meta="Featured"
          onPress={() => router.push({ pathname: '/look/[id]', params: { id: lead.id } })}
        />
      ) : null}
    </View>
  );
}
