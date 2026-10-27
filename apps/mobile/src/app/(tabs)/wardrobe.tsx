import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { useMemo, useState } from 'react';
import { FlatList, Platform, Pressable, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import {
  AspectRatio,
  BottomTabInset,
  Colors,
  Display,
  Motion,
  Radius,
  Spacing,
} from '@/constants/theme';
import {
  AVAILABILITY_LABEL,
  SAMPLE_WARDROBE,
  WARDROBE_FILTERS,
  filterWardrobe,
  type SampleGarment,
} from '@/features/wardrobe/sample';
import { useScheme } from '@/hooks/use-theme';

type FilterId = (typeof WARDROBE_FILTERS)[number]['id'];

/**
 * Wardrobe — the user's own items, filters, collections and capture (§3, §5).
 *
 * Shows a sample wardrobe rather than an empty grid, which §3 asks for explicitly:
 * someone should be able to see styling work before photographing forty garments.
 * The banner says it is a sample and never stops saying it — a demonstration that
 * quietly passes for the user's own data is worse than none, because the moment they
 * add a real garment they cannot tell which is which.
 */
export default function WardrobeScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [filter, setFilter] = useState<FilterId>('all');

  const columns = width >= 700 ? 4 : 3;
  const gutter = Spacing.two;

  const visible = useMemo(() => filterWardrobe(SAMPLE_WARDROBE, filter), [filter]);
  const availableCount = SAMPLE_WARDROBE.filter(
    (garment) => garment.availability === 'available',
  ).length;

  return (
    <FlatList
      style={{ backgroundColor: colors.background }}
      data={visible}
      keyExtractor={(item) => item.id}
      numColumns={columns}
      key={columns}
      columnWrapperStyle={{ gap: gutter }}
      contentContainerStyle={{
        paddingTop: insets.top + Spacing.three,
        paddingHorizontal: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        gap: gutter,
      }}
      showsVerticalScrollIndicator={false}
      ListHeaderComponent={
        <Header
          filter={filter}
          onFilter={setFilter}
          total={SAMPLE_WARDROBE.length}
          available={availableCount}
          gutter={gutter}
        />
      }
      renderItem={({ item }) => <GarmentCell garment={item} />}
    />
  );
}

function GarmentCell({ garment }: { garment: SampleGarment }) {
  const colors = Colors[useScheme()];
  const unavailable = garment.availability !== 'available';
  const badge = AVAILABILITY_LABEL[garment.availability];

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${garment.name}. ${garment.confirmed.colour} ${garment.category}${
        badge ? `. ${badge}` : ''
      }`}
      onPress={() => {
        if (Platform.OS !== 'web') void Haptics.selectionAsync();
      }}
      style={({ pressed }) => ({ flex: 1, gap: Spacing.one, opacity: pressed ? 0.7 : 1 })}>
      <View
        style={{
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
          borderWidth: 1,
          borderColor: colors.border,
        }}>
        <Image
          source={garment.image}
          placeholder={garment.blurhash ? { blurhash: garment.blurhash } : undefined}
          cachePolicy="memory-disk"
          contentFit="cover"
          transition={Motion.base}
          accessible={false}
          style={{
            width: '100%',
            aspectRatio: AspectRatio.garment,
            // Dimmed rather than hidden: an unavailable garment still exists, and
            // hiding it would make the wardrobe look wrong.
            opacity: unavailable ? 0.45 : 1,
          }}
        />
        {badge ? (
          <View
            style={{
              position: 'absolute',
              left: Spacing.one,
              bottom: Spacing.one,
              paddingHorizontal: Spacing.two,
              paddingVertical: 2,
              borderRadius: Radius.full,
              backgroundColor: 'rgba(16,12,11,0.72)',
            }}>
            <ThemedText
              type="small"
              style={{ fontSize: 9, letterSpacing: 0.6, color: 'rgba(255,255,255,0.92)' }}>
              {badge}
            </ThemedText>
          </View>
        ) : null}
      </View>

      <ThemedText type="small" numberOfLines={1} style={{ fontSize: 12 }}>
        {garment.name}
      </ThemedText>
    </Pressable>
  );
}

function Header({
  filter,
  onFilter,
  total,
  available,
  gutter,
}: {
  filter: FilterId;
  onFilter: (id: FilterId) => void;
  total: number;
  available: number;
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
          {available} of {total} ready to wear
        </ThemedText>
        <ThemedText
          style={{
            fontFamily: Display.regular,
            fontSize: 44,
            lineHeight: 46,
            letterSpacing: -0.5,
            color: colors.text,
          }}>
          Wardrobe
        </ThemedText>
      </View>

      {/* Says "sample" permanently, not just on first run. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
          padding: Spacing.three,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          borderWidth: 1,
          borderColor: colors.accent,
        }}>
        <View style={{ flex: 1, gap: 2 }}>
          <ThemedText type="smallBold" style={{ color: colors.accent, fontSize: 12 }}>
            Sample wardrobe
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 12 }}>
            Demonstration items so you can try styling before adding your own.
          </ThemedText>
        </View>
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
        {WARDROBE_FILTERS.map((option) => {
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
                borderColor: active ? colors.text : colors.border,
                opacity: pressed ? 0.6 : 1,
              })}>
              <ThemedText
                type="small"
                style={{ fontSize: 13, color: active ? colors.background : colors.textSecondary }}>
                {option.label}
              </ThemedText>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
