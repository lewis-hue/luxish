import { useMemo, useState } from 'react';
import { FlatList, Pressable, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { StyleTile } from '@/components/ui/style-tile';
import { BottomTabInset, Colors, Fonts, Radius, Spacing } from '@/constants/theme';
import { STYLE_CATEGORIES, type StyleCategory } from '@/features/discover/collections';
import { useScheme } from '@/hooks/use-theme';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'casual', label: 'Casual' },
  { id: 'smart_casual', label: 'Smart casual' },
  { id: 'business', label: 'Office' },
  { id: 'formal', label: 'Formal' },
  { id: 'black_tie', label: 'Evening' },
] as const;

/**
 * Discover — style tiles, curated inspiration and search entry (§3).
 *
 * Virtualised two-column grid (§17: virtualised feeds, restrained prefetch). The
 * column count is derived from width so the layout holds on a small phone and a
 * tablet without a second screen.
 */
export default function DiscoverScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('all');

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.two;

  const data = useMemo(
    () =>
      filter === 'all'
        ? STYLE_CATEGORIES
        : STYLE_CATEGORIES.filter((c) => c.formality === filter),
    [filter],
  );

  return (
    <FlatList
      style={{ backgroundColor: colors.background }}
      data={data}
      keyExtractor={(item) => item.id}
      numColumns={columns}
      // Remount on column change — FlatList cannot alter numColumns in place.
      key={columns}
      columnWrapperStyle={columns > 1 ? { gap: gutter } : undefined}
      contentContainerStyle={{
        paddingTop: insets.top + Spacing.two,
        paddingHorizontal: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.four,
        gap: gutter,
      }}
      // Keep memory bounded on mid-range devices rather than retaining every row.
      windowSize={5}
      initialNumToRender={6}
      removeClippedSubviews
      ListHeaderComponent={
        <Header filter={filter} onFilter={setFilter} count={data.length} />
      }
      renderItem={({ item }) => <Tile category={item} />}
      ListEmptyComponent={
        <View style={{ paddingVertical: Spacing.six, alignItems: 'center' }}>
          <ThemedText type="small" themeColor="textSecondary">
            No collections in this category yet.
          </ThemedText>
        </View>
      }
    />
  );
}

function Tile({ category }: { category: StyleCategory }) {
  return (
    <StyleTile
      style={{ flex: 1 }}
      asset={category.cover}
      title={category.title}
      subtitle={category.subtitle}
      meta={category.lookCount === null ? null : `${category.lookCount} looks`}
      // Collection detail arrives with the Discover detail route; the tile is
      // deliberately inert rather than navigating to a stub.
      onPress={undefined}
    />
  );
}

function Header({
  filter,
  onFilter,
  count,
}: {
  filter: string;
  onFilter: (id: (typeof FILTERS)[number]['id']) => void;
  count: number;
}) {
  const colors = Colors[useScheme()];

  return (
    <View style={{ gap: Spacing.three, marginBottom: Spacing.three }}>
      <View style={{ gap: Spacing.one }}>
        {/* Serif display face carries the editorial direction. */}
        <ThemedText
          style={{
            fontFamily: Fonts.serif,
            fontSize: 40,
            lineHeight: 44,
            color: colors.text,
          }}>
          Discover
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          {count} style {count === 1 ? 'collection' : 'collections'}
        </ThemedText>
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
        {FILTERS.map((f) => {
          const active = f.id === filter;
          return (
            <Pressable
              key={f.id}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onFilter(f.id)}
              // 44pt minimum touch target (§3).
              hitSlop={8}
              style={({ pressed }) => ({
                minHeight: 36,
                justifyContent: 'center',
                paddingHorizontal: Spacing.three,
                borderRadius: Radius.full,
                backgroundColor: active ? colors.accent : 'transparent',
                borderWidth: active ? 0 : 1,
                borderColor: colors.border,
                opacity: pressed ? 0.7 : 1,
              })}>
              <ThemedText
                type="small"
                style={{ color: active ? colors.accentText : colors.textSecondary }}>
                {f.label}
              </ThemedText>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
