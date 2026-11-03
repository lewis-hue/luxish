import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import Animated from 'react-native-reanimated';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import {
  AspectRatio,
  BottomTabInset,
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
  toneColor,
  type Tone,
  labelType,
} from '@/constants/theme';
import { useFavouriteGarments } from '@/features/discover/saved';
import { SymbolView } from 'expo-symbols';

import { useFolders } from '@/api/queries/collections';
import { useBulkDeleteGarments } from '@/api/queries/wardrobe';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { SelectionBar } from '@/features/wardrobe/selection-bar';
import { AVAILABILITY_LABEL, AVAILABILITY_TONE } from '@/features/wardrobe/sample';
import { useWardrobe, type WardrobeEntry } from '@/features/wardrobe/store';
import { SLOTS, SLOT_LABELS, type Slot } from '@/features/taxonomy';
import { useScheme } from '@/hooks/use-theme';

import {
  MotionPressable,
  successFeedback,
  tapFeedback,
  usePopMotion,
} from '@/components/ui/motion';
import { EmptyState } from '@/components/ui/empty-state';
import { matchesQuery, SearchField } from '@/components/ui/search-field';
import { pushFavourite } from '@/features/wardrobe/sync';
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
export default function ClosetScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);
  const capture = useGarmentCapture();
  const [filter, setFilter] = useState<FilterId>('all');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<WardrobeEntry | null>(null);
  /**
   * Garment ids picked for a bulk action. Empty means not in selection
   * mode at all — the mode *is* the selection, so there is no separate
   * flag to keep in step with it.
   */
  const [picked, setPicked] = useState<readonly string[]>([]);
  const folders = useFolders(true);
  const bulkDelete = useBulkDeleteGarments();

  const columns = width >= 700 ? 4 : 3;
  const gutter = Spacing.two;
  /**
   * The width of one cell, computed rather than flexed.
   *
   * A cell styled `flex: 1` fills the row it is in — which is correct for
   * every full row and wrong for the last one. Nine garments in a
   * three-column grid left the ninth alone on its row at triple width, and
   * a wardrobe whose final item is three times the size of the rest reads
   * as a layout fault, because it is one. `columnWrapperStyle` puts a
   * `gutter` between cells, so the row has `columns - 1` of them to give
   * away before the cells get their share.
   */
  const cell =
    (width - Spacing.three * 2 - gutter * (columns - 1)) / columns;

  const visible = useMemo(() => {
    const grouped =
      filter === 'all'
        ? wardrobe.entries
        : filter === 'favourites'
          ? wardrobe.entries.filter((entry) => entry.isFavourite)
          : wardrobe.entries.filter((entry) => entry.slot === filter);
    // Searched across what the user named it and what the model read off it,
    // so "denim" finds a pair of jeans called "work trousers".
    return grouped.filter((entry) =>
      matchesQuery(
        query,
        entry.name,
        entry.categoryId,
        entry.slot,
        entry.inferred?.colour,
        entry.inferred?.material,
        entry.inferred?.pattern,
      ),
    );
  }, [filter, query, wardrobe.entries]);

  const ready = wardrobe.entries.filter((entry) => entry.availability === 'available').length;

  /**
   * Heart a garment here and on the server.
   *
   * Local first, so the heart fills in on the tap rather than after a round
   * trip. The server copy matters because the stylist orders its candidates
   * by it, and that list is capped: a favourite the server never heard about
   * is one the stylist is never shown.
   */
  const toggleFavourite = async (entry: WardrobeEntry) => {
    const wasFavourite = favourites.has(entry.id);
    await favourites.toggle(entry.id);
    if (entry.serverId) {
      void pushFavourite({
        serverId: entry.serverId,
        isFavourite: !wasFavourite,
      });
    }
  };

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
    if (result === 'unavailable') {
      // Said out loud. This used to reject into nothing, and the
      // camera read as a button that did nothing at all.
      Alert.alert(
        'That could not be opened',
        'The camera is not available right now. Choosing from your photos still works.',
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
        refreshControl={
          // Pulling down is the gesture people already try when a list looks
          // stale, and this wardrobe genuinely can be: garments detected in a
          // photograph are created on the server, so the device has to go and
          // ask. It also gives someone a way to recover from a failed sync
          // without hunting for a button.
          <RefreshControl
            refreshing={wardrobe.refreshing}
            onRefresh={() => void wardrobe.refresh()}
            // The accent, like every other refresh in the app: this
            // one is kept rather than replaced by the shared control
            // because it pulls the wardrobe specifically, but it
            // should not look like a different app while it does.
            tintColor={colors.accent}
            colors={[colors.accent]}
            progressBackgroundColor={colors.background}
          />
        }
        ListHeaderComponent={
          <Header
            filter={filter}
            onFilter={setFilter}
            query={query}
            onQuery={setQuery}
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
            width={cell}
            picking={picked.length > 0}
            picked={picked.includes(item.id)}
            onPress={() => {
              // In selection mode a tap adds and removes; outside it, a
              // tap still opens the garment. One gesture, two meanings,
              // decided by the mode rather than by a modifier.
              if (picked.length > 0) {
                void tapFeedback();
                setPicked((current) =>
                  current.includes(item.id)
                    ? current.filter((id) => id !== item.id)
                    : [...current, item.id],
                );
              } else {
                setSelected(item);
              }
            }}
            onLongPress={() => {
              void tapFeedback();
              setPicked((current) =>
                current.includes(item.id) ? current : [...current, item.id],
              );
            }}
            onToggleFavourite={() => void toggleFavourite(item)}
          />
        )}
        ListEmptyComponent={
          // One line of fact, one way out, and the way out depends on why the
          // grid is empty: a failed search wants the filters cleared, an
          // empty wardrobe wants the camera.
          <EmptyState
            status="empty"
            title={
              query.trim()
                ? 'No match'
                : filter === 'favourites'
                  ? 'Nothing loved yet'
                  : 'Nothing here yet'
            }
            body={
              query.trim()
                ? `Nothing matches "${query.trim()}". Try a colour, a material, or part of a name.`
                : filter === 'favourites'
                  ? 'Tap the heart on anything you love and it will appear here.'
                  : 'Photograph a garment and it will be sorted and tidied for you.'
            }
            action={
              query.trim() || filter !== 'all'
                ? {
                    label: 'Show everything',
                    onPress: () => {
                      void tapFeedback();
                      setQuery('');
                      setFilter('all');
                    },
                  }
                : {
                    label: 'Photograph a garment',
                    onPress: () => {
                      void tapFeedback();
                      void add('camera');
                    },
                  }
            }
          />
        }
      />

      <SelectionBar
        count={picked.length}
        folders={folders.data ?? []}
        selectedIds={picked}
        onClear={() => setPicked([])}
        onDelete={() => {
          const ids = [...picked];
          setPicked([]);
          bulkDelete.mutate(ids, {
            onSuccess: () => {
              void successFeedback();
              void wardrobe.refresh();
            },
            onError: () =>
              Alert.alert('Could not remove those', 'Try again in a moment.'),
          });
        }}
      />

      <GarmentSheet
        entry={selected}
        onClose={() => setSelected(null)}
        onRename={wardrobe.rename}
        onSetAvailability={wardrobe.setAvailability}
        onDelete={wardrobe.remove}
        onToggleFavourite={async (id) => {
          const entry = wardrobe.entries.find((candidate) => candidate.id === id);
          if (entry) await toggleFavourite(entry);
        }}
        isFavourite={selected ? favourites.has(selected.id) : false}
      />
    </>
  );
}

/**
 * The single thing a tile should say about where a garment has got to.
 *
 * Ordered by what the person can act on. An error comes first because it is
 * the only state that asks anything of them; work in progress comes next and
 * reads as busy; "not uploaded" is last, because a garment sitting on the
 * device is a fact rather than a problem. A finished garment says nothing at
 * all, which is the point: a wardrobe of badges is a wardrobe nobody reads.
 *
 * `needsSync` is what separates uploading from sorting: it is set from the
 * absence of a server id, so while it holds the bytes are still going up, and
 * once it clears the server has the photograph and is working on it.
 */
function garmentProgress(entry: WardrobeEntry): {
  label: string;
  spoken: string;
  busy: boolean;
  tone: Tone;
} | null {
  if (entry.syncError) {
    return {
      label: entry.syncError,
      spoken: entry.syncError,
      busy: false,
      tone: 'warning',
    };
  }
  if (entry.status === 'pending') {
    return entry.needsSync
      ? { label: 'Uploading', spoken: 'Uploading', busy: true, tone: 'muted' }
      : { label: 'Sorting', spoken: 'Sorting', busy: true, tone: 'muted' };
  }
  if (entry.needsSync) {
    return {
      label: 'Not uploaded',
      spoken: 'Not uploaded yet',
      busy: false,
      tone: 'muted',
    };
  }
  if (entry.isRendered) {
    // Said plainly, and never only in colour (WCAG 1.4.1): this picture is a
    // drawing of a garment like this one, because the photograph hid too much
    // of the real one to cut it out. Someone deciding what to wear can act on
    // that; someone who thinks it is a photo of their own garment cannot.
    return {
      label: 'Illustrated',
      spoken: 'Illustrated, not a photo of this garment',
      busy: false,
      tone: 'accent',
    };
  }
  return null;
}

function GarmentCell({
  entry,
  index,
  width,
  picking,
  picked,
  onPress,
  onLongPress,
  onToggleFavourite,
}: {
  entry: WardrobeEntry;
  index: number;
  width: number;
  /** Selection mode is on, so the whole grid shows its checkboxes. */
  picking?: boolean;
  picked?: boolean;
  onPress: () => void;
  onLongPress?: () => void;
  onToggleFavourite: () => void;
}) {
  const colors = Colors[useScheme()];
  const favourite = usePopMotion();
  const unavailable = entry.availability !== 'available';
  const badge = AVAILABILITY_LABEL[entry.availability];
  const progress = garmentProgress(entry);

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={`${entry.name}${badge ? `. ${badge}` : ''}`}
      accessibilityState={picking ? { selected: picked } : undefined}
      index={index}
      onPress={onPress}
      onLongPress={onLongPress}
      // A fixed width, not `flex: 1`. See the note on `cell` above: flexing
      // stretches whatever is alone on the last row.
      style={{ width, gap: Spacing.one }}>
      <View
        style={{
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
          borderWidth: 1,
          // The selected cell takes the accent border, which reads at
          // grid size where a tick alone does not.
          borderColor: picked ? colors.accent : colors.border,
        }}>
        <Image
          source={entry.image ?? (entry.uri ? { uri: entry.uri } : undefined)}
          // The wardrobe recycles too, and a cut-out flashing the
          // previous garment reads worse than anywhere else: these
          // are meant to be the clothes you own.
          recyclingKey={entry.id}
          placeholder={
            // ThumbHash first: it is the only one of the two that survives a
            // cut-out's transparency. BlurHash remains correct for the
            // bundled sample garments, which are opaque photographs.
            entry.thumbhash
              ? { thumbhash: entry.thumbhash }
              : entry.blurhash
                ? { blurhash: entry.blurhash }
                : undefined
          }
          cachePolicy="memory-disk"
          contentFit="cover"
          transition={ImageFade}
          accessible={false}
          style={{
            width: '100%',
            aspectRatio: AspectRatio.garment,
            // Dimmed, not hidden: an unavailable garment still exists, and hiding
            // it makes the wardrobe look wrong.
            opacity: unavailable ? 0.45 : 1,
          }}
        />

        {/* The tick, over the photograph, only while picking. Top-left
            so it never sits under the favourite control, and filled when
            on because an empty circle at this size is easy to misread as
            a smudge on the picture. */}
        {picking ? (
          <View
            style={{
              position: 'absolute',
              top: Spacing.two,
              left: Spacing.two,
              width: 26,
              height: 26,
              borderRadius: Radius.full,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: picked ? colors.accent : '#00000059',
            }}>
            <SymbolView
              name={{
                ios: picked ? 'checkmark' : 'circle',
                android: picked ? 'check' : 'radio_button_unchecked',
                web: 'check',
              }}
              size={15}
              tintColor="#FFFFFF"
            />
          </View>
        ) : null}

        {progress ? (
          // One badge, and never a scrim over the photograph.
          //
          // The photograph is the content. Someone has just taken it, it is
          // the best thing on the screen, and covering it with a dimming
          // layer and a full-cell spinner made a ten-second wait feel like a
          // stall on a cell that had stopped working. A quiet badge on a
          // visible garment reads as a garment that is already here and
          // nearly finished, which is what is actually true.
          //
          // It also says one thing at a time. Upload and sorting used to
          // render together, so a garment on its way to the server announced
          // "Not uploaded" underneath a spinner that meant the server was
          // working on it.
          <View
            accessible
            accessibilityLabel={`${entry.name}. ${progress.spoken}`}
            accessibilityState={{ busy: progress.busy }}
            style={{
              position: 'absolute',
              left: Spacing.one,
              top: Spacing.one,
              maxWidth: '85%',
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.one,
              paddingHorizontal: Spacing.two,
              paddingVertical: Spacing.one,
              borderRadius: Radius.full,
              backgroundColor: 'rgba(16,12,11,0.72)',
            }}>
            {progress.busy ? (
              // Small enough to sit on the badge's baseline rather than
              // dominate it. An indeterminate indicator is exempt from WCAG
              // 2.2.2, which covers moving content a person has to read.
              <ActivityIndicator
                size="small"
                color="rgba(255,255,255,0.94)"
                style={{ width: 10, height: 10, transform: [{ scale: 0.6 }] }}
              />
            ) : (
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: Radius.full,
                  backgroundColor: toneColor(colors, progress.tone),
                }}
              />
            )}
            <ThemedText
              type="small"
              numberOfLines={1}
              style={{
                flexShrink: 1,
                fontSize: FontSize.meta,
                color: 'rgba(255,255,255,0.94)',
              }}>
              {progress.label}
            </ThemedText>
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
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.one,
              paddingHorizontal: Spacing.two,
              paddingVertical: Spacing.one,
              borderRadius: Radius.full,
              backgroundColor: 'rgba(16,12,11,0.72)',
            }}>
            {/*
              A coloured dot beside the word, never colour alone. WCAG 1.4.1
              forbids colour as the sole carrier of meaning, and the pill sits
              over an unknown photograph where a tint would be unreliable
              anyway. The text stays white so it is legible regardless; the dot
              is what carries the state at a glance.
            */}
            <View
              style={{
                width: 6,
                height: 6,
                borderRadius: Radius.full,
                backgroundColor: toneColor(colors, AVAILABILITY_TONE[entry.availability]),
              }}
            />
            <ThemedText
              type="small"
              style={{ fontSize: FontSize.meta, color: 'rgba(255,255,255,0.94)' }}>
              {badge}
            </ThemedText>
          </View>
        ) : null}
      </View>

      <View style={{ gap: Spacing.half }}>
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
  query,
  onQuery,
  total,
  ready,
  favouriteCount,
  busy,
  onAdd,
  gutter,
}: {
  filter: FilterId;
  onFilter: (id: FilterId) => void;
  query: string;
  onQuery: (next: string) => void;
  total: number;
  ready: number;
  favouriteCount: number;
  busy: boolean;
  onAdd: (source: 'camera' | 'library') => void;
  gutter: number;
}) {
  const colors = Colors[useScheme()];
  /**
   * Whether the row is showing search or the filters.
   *
   * Seeded open when there is already a query, so a header that
   * re-renders mid-search does not close the field somebody is
   * typing in.
   */
  const [searching, setSearching] = useState(query.length > 0);

  const filters: { id: FilterId; label: string }[] = [
    { id: 'all', label: 'All' },
    ...SLOTS.map((slot) => ({ id: slot as FilterId, label: SLOT_LABELS[slot] })),
    { id: 'favourites', label: `Loved${favouriteCount ? ` (${favouriteCount})` : ''}` },
  ];

  return (
    // Tighter than it was. Four full-width blocks at `Spacing.three`
    // apart pushed the first row of clothes a third of the way down
    // the screen, on the one page where the clothes are the point.
    <View style={{ gap: Spacing.two, marginBottom: gutter }}>
      {/* The count beside the title rather than under it: it is four
          words, and a line of its own spent them like a heading. */}
      <View style={{ gap: Spacing.half }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          animateEntrance={false}
          hitSlop={Spacing.two}
          onPress={() => {
            void tapFeedback();
            if (router.canGoBack()) router.back();
            else router.replace('/wardrobe');
          }}
          style={{
            width: TapTarget,
            height: TapTarget,
            marginLeft: -Spacing.two,
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{
              ios: 'chevron.left',
              android: 'arrow_back',
              web: 'arrow_back',
            }}
            size={22}
            tintColor={colors.text}
          />
        </MotionPressable>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(28, 800), lineHeight: 34 }}>
          Wardrobe
        </ThemedText>
        <ThemedText
          themeColor="textSecondary"
          numberOfLines={1}
          style={labelType(FontSize.footnote, 400)}>
          {ready} of {total} ready
        </ThemedText>
      </View>

      {/* Adding a piece, where the pieces are.

          The assistant's `+` on the wardrobe tab also adds, which is
          the shortcut; this is the one on the page somebody opened to
          manage their clothes. */}
      <View style={{ flexDirection: 'row', gap: Spacing.two }}>
        <AddButton label="Add a piece" onPress={() => onAdd('camera')} busy={busy} primary />
        <AddButton label="From photos" onPress={() => onAdd('library')} busy={busy} />
      </View>

      {/* Search shares the filters' row instead of taking one of its
          own.

          It was a full-width pill directly under the ask bar - same
          shape, same height, same grey - so the top of the page read
          as two of the same control stacked, and the clothes started
          a third of the way down. A magnifier beside the filters is
          the row people already scan to narrow things down, and
          searching is the same act. */}
      {searching ? (
        <View
          style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.two }}>
          <View style={{ flex: 1 }}>
            <SearchField
              value={query}
              onChangeText={onQuery}
              placeholder="Search your wardrobe"
              accessibilityLabel="Search your wardrobe"
            />
          </View>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Close search"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              onQuery('');
              setSearching(false);
            }}
            style={{
              minHeight: TapTarget,
              justifyContent: 'center',
              paddingHorizontal: Spacing.one,
            }}>
            <ThemedText type="smallBold" style={{ color: colors.accent }}>
              Done
            </ThemedText>
          </MotionPressable>
        </View>
      ) : (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.four,
        }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Search your wardrobe"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            setSearching(true);
          }}
          style={{ justifyContent: 'center' }}>
          <SymbolView
            name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }}
            size={20}
            tintColor={colors.text}
          />
        </MotionPressable>
        {filters.map((option) => {
          const active = option.id === filter;
          return (
            <Pressable
              key={option.id}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => onFilter(option.id)}
              hitSlop={6}
              // A rule under the word rather than a box around it,
              // the same way the board's categories read. Seven
              // outlined pills over a grid of cut-outs is seven boxes
              // competing with the clothes.
              style={({ pressed }) => ({
                minHeight: 40,
                justifyContent: 'center',
                borderBottomWidth: 2,
                borderBottomColor: active ? colors.text : 'transparent',
                opacity: pressed ? 0.6 : 1,
              })}>
              <ThemedText
                style={{
                  ...labelType(FontSize.body, 800),
                  color: active ? colors.text : colors.textSecondary,
                }}>
                {option.label}
              </ThemedText>
            </Pressable>
          );
        })}
      </ScrollView>
      )}
    </View>
  );
}


/** One way to add a piece. Filled for the camera, quiet for the library. */
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
        backgroundColor: primary ? colors.accent : colors.backgroundElement,
        opacity: busy ? 0.6 : pressed ? 0.75 : 1,
      })}>
      {busy ? (
        <ActivityIndicator color={primary ? colors.accentText : colors.text} />
      ) : (
        <ThemedText
          style={{
            ...labelType(FontSize.body, 800),
            color: primary ? colors.accentText : colors.text,
          }}>
          {label}
        </ThemedText>
      )}
    </Pressable>
  );
}
