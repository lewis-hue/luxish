import { Image } from 'expo-image';
import { useMemo, useState } from 'react';
import Animated from 'react-native-reanimated';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import {
  AspectRatio,
  BottomTabInset,
  Colors,
  Display,
  FontSize,
  Motion,
  Radius,
  Spacing,
  Tracking,
} from '@/constants/theme';
import { useFavouriteGarments } from '@/features/discover/saved';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { AVAILABILITY_LABEL } from '@/features/wardrobe/sample';
import { useWardrobe, type WardrobeEntry } from '@/features/wardrobe/store';
import { SLOTS, SLOT_LABELS, type Slot } from '@/features/taxonomy';
import { useScheme } from '@/hooks/use-theme';

import {
  MotionPressable,
  successFeedback,
  tapFeedback,
  usePopMotion,
} from '@/components/ui/motion';
import { GarmentSheet } from '@/features/wardrobe/garment-sheet';

type FilterId = 'all' | Slot | 'favourites';

/**
 * Wardrobe — the user's own items, filters, capture (§3, §5).
 *
 * Filters are the five taxonomy slots rather than ad-hoc groupings, so what the user
 * sees matches what the stylist reasons about. Favourites get their own filter
 * because "show me the clothes I love" is a real and frequent request.
 *
 * The sample wardrobe stays visible alongside real garments and stays labelled, so
 * a demonstration item can never be mistaken for something the user owns.
 */
export default function WardrobeScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);
  const capture = useGarmentCapture();
  const [filter, setFilter] = useState<FilterId>('all');
  const [selected, setSelected] = useState<WardrobeEntry | null>(null);

  const columns = width >= 700 ? 4 : 3;
  const gutter = Spacing.two;

  const visible = useMemo(() => {
    if (filter === 'all') return wardrobe.entries;
    if (filter === 'favourites') return wardrobe.entries.filter((entry) => entry.isFavourite);
    return wardrobe.entries.filter((entry) => entry.slot === filter);
  }, [filter, wardrobe.entries]);

  const ready = wardrobe.entries.filter((entry) => entry.availability === 'available').length;

  const add = async (source: 'camera' | 'library') => {
    const result =
      source === 'camera' ? await capture.photograph() : await capture.pickFromLibrary();

    if (result === 'denied') {
      Alert.alert(
        source === 'camera' ? 'Camera access needed' : 'Photo access needed',
        'Grant access in Settings to add your clothes. Everything else keeps working.',
      );
      return;
    }
    if (result === 'cancelled' || typeof result === 'string') return;

    await wardrobe.addMany(result);
    void successFeedback();
  };

  return (
    <>
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
            total={wardrobe.entries.length}
            ready={ready}
            favouriteCount={favourites.count}
            busy={capture.busy}
            onAdd={add}
            gutter={gutter}
          />
        }
        renderItem={({ item, index }) => (
          <GarmentCell
            entry={item}
            index={index}
            onPress={() => setSelected(item)}
            onToggleFavourite={() => void favourites.toggle(item.id)}
          />
        )}
        ListEmptyComponent={
          <View style={{ paddingVertical: Spacing.six, alignItems: 'center' }}>
            <ThemedText type="small" themeColor="textSecondary">
              {filter === 'favourites'
                ? 'Tap the heart on anything you love and it will appear here.'
                : 'Nothing in this group yet.'}
            </ThemedText>
          </View>
        }
      />

      <GarmentSheet
        entry={selected}
        onClose={() => setSelected(null)}
        onRename={wardrobe.rename}
        onSetAvailability={wardrobe.setAvailability}
        onDelete={wardrobe.remove}
        onToggleFavourite={favourites.toggle}
        isFavourite={selected ? favourites.has(selected.id) : false}
      />
    </>
  );
}

function GarmentCell({
  entry,
  index,
  onPress,
  onToggleFavourite,
}: {
  entry: WardrobeEntry;
  index: number;
  onPress: () => void;
  onToggleFavourite: () => void;
}) {
  const colors = Colors[useScheme()];
  const favourite = usePopMotion();
  const unavailable = entry.availability !== 'available';
  const badge = AVAILABILITY_LABEL[entry.availability];

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={`${entry.name}${badge ? `. ${badge}` : ''}`}
      index={index}
      onPress={onPress}
      style={{ flex: 1, gap: Spacing.one }}>
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
          source={entry.image ?? (entry.uri ? { uri: entry.uri } : undefined)}
          placeholder={entry.blurhash ? { blurhash: entry.blurhash } : undefined}
          cachePolicy="memory-disk"
          contentFit="cover"
          transition={Motion.base}
          accessible={false}
          style={{
            width: '100%',
            aspectRatio: AspectRatio.garment,
            // Dimmed, not hidden: an unavailable garment still exists, and hiding
            // it makes the wardrobe look wrong.
            opacity: unavailable ? 0.45 : 1,
          }}
        />

        {entry.status === 'pending' ? (
          <View
            accessible
            accessibilityLabel={`Sorting ${entry.name}`}
            accessibilityState={{ busy: true }}
            style={{
              position: 'absolute',
              inset: 0,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'rgba(16,12,11,0.35)',
            }}>
            <ActivityIndicator color="#FFFFFF" />
          </View>
        ) : null}

        {/* Favourite is a direct tap on the cell — burying "I love this" behind a
            detail screen means it never gets used. */}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={
            entry.isFavourite ? `Remove ${entry.name} from favourites` : `Favourite ${entry.name}`
          }
          accessibilityState={{ selected: entry.isFavourite }}
          onPress={() => {
            // Pop on the way *in* only. A heart that silently changes colour
            // is easy to miss, and missing it means tapping twice.
            if (!entry.isFavourite) favourite.pop();
            void tapFeedback();
            onToggleFavourite();
          }}
          hitSlop={12}
          style={{
            position: 'absolute',
            top: Spacing.one,
            right: Spacing.one,
            width: 28,
            height: 28,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.full,
            backgroundColor: 'rgba(16,12,11,0.5)',
          }}>
          <Animated.View style={favourite.style}>
            <ThemedText
              style={{
                fontSize: FontSize.footnote,
                color: entry.isFavourite ? '#FF8FA8' : '#FFFFFF',
              }}>
              {entry.isFavourite ? '♥' : '♡'}
            </ThemedText>
          </Animated.View>
        </Pressable>

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
              style={{ fontSize: FontSize.meta, color: 'rgba(255,255,255,0.94)' }}>
              {badge}
            </ThemedText>
          </View>
        ) : null}
      </View>

      <View style={{ gap: 1 }}>
        <ThemedText type="small" numberOfLines={1} style={{ fontSize: FontSize.caption }}>
          {entry.name}
        </ThemedText>
        {entry.isSample ? (
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            Sample
          </ThemedText>
        ) : null}
      </View>
    </MotionPressable>
  );
}

function Header({
  filter,
  onFilter,
  total,
  ready,
  favouriteCount,
  busy,
  onAdd,
  gutter,
}: {
  filter: FilterId;
  onFilter: (id: FilterId) => void;
  total: number;
  ready: number;
  favouriteCount: number;
  busy: boolean;
  onAdd: (source: 'camera' | 'library') => void;
  gutter: number;
}) {
  const colors = Colors[useScheme()];

  const filters: { id: FilterId; label: string }[] = [
    { id: 'all', label: 'All' },
    ...SLOTS.map((slot) => ({ id: slot as FilterId, label: SLOT_LABELS[slot] })),
    { id: 'favourites', label: `Loved${favouriteCount ? ` (${favouriteCount})` : ''}` },
  ];

  return (
    <View style={{ gap: Spacing.three, marginBottom: gutter }}>
      <View style={{ gap: Spacing.half }}>
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{
            fontSize: FontSize.meta,
            letterSpacing: Tracking.wide,
            textTransform: 'uppercase',
          }}>
          {ready} of {total} ready to wear
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

      <View style={{ flexDirection: 'row', gap: Spacing.two }}>
        <AddButton label="Take a photo" onPress={() => onAdd('camera')} busy={busy} primary />
        <AddButton label="Choose photos" onPress={() => onAdd('library')} busy={busy} />
      </View>

      <ThemedText
        type="small"
        themeColor="textSecondary"
        style={{ fontSize: FontSize.caption }}>
        Up to 20 at once. Sorted and tidied automatically. Rename anything.
      </ThemedText>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
        {filters.map((option) => {
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

function AddButton({
  label,
  onPress,
  busy,
  primary,
}: {
  label: string;
  onPress: () => void;
  busy: boolean;
  primary?: boolean;
}) {
  const colors = Colors[useScheme()];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ busy, disabled: busy }}
      disabled={busy}
      onPress={onPress}
      style={({ pressed }) => ({
        flex: 1,
        minHeight: 46,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: primary ? colors.accent : 'transparent',
        borderWidth: 1,
        borderColor: primary ? colors.accent : colors.border,
        opacity: busy ? 0.6 : pressed ? 0.75 : 1,
      })}>
      {busy ? (
        <ActivityIndicator color={primary ? colors.accentText : colors.text} />
      ) : (
        <ThemedText type="smallBold" style={{ color: primary ? colors.accentText : colors.text }}>
          {label}
        </ThemedText>
      )}
    </Pressable>
  );
}
