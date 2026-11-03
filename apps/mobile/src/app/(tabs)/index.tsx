import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import {
  Alert,
  Pressable,
  ScrollView,
  View,
  useWindowDimensions,
} from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useBoard,
  useFeedGroups,
  useSaveFit,
  type FeedFit,
} from '@/api/queries/discover-feed';
import * as ImagePicker from 'expo-image-picker';
import { SymbolView } from 'expo-symbols';

import { ThemedText } from '@/components/themed-text';
import { InboxButton } from '@/components/ui/inbox-button';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { useIdeas, type Door } from '@/api/queries/explore';
import { FitCard } from '@/features/feed/fit-card';
import { IdeasShelf } from '@/features/feed/ideas-shelf';
import { PinActions, type PinSubject } from '@/components/ui/pin-actions';
import { CreateSheet } from '@/features/feed/create-sheet';
import { ShareSheet } from '@/features/feed/share-sheet';
import { useScreenshotPrompt } from '@/features/feed/use-screenshot';
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
import { BRAND } from '@/branding';
import { useAuth } from '@/features/auth/session';
import {
} from '@/features/discover/collections';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { useReturnedToApp } from '@/hooks/use-returned-to-app';
import { useScheme } from '@/hooks/use-theme';

/**
 * Discover — twenty collections, arranged by the question people actually ask.
 *
 * It used to be one lead tile over a flat grid of twelve, which gives the eye
 * nowhere to land and tells you nothing: every collection reads as equally
 * important, and "Office" sits beside "Rainy season" as though they answered
 * the same question. They do not.
 *
 * So the browse state is **shelves**, grouped by how dressed up something is,
 * because that is the question. Someone opening this is deciding what to wear
 * to a thing, and "how formal is it" is the first fork in that decision. The
 * groupings come from each collection's own `formality`, so the structure is
 * read off the data rather than imposed on it.
 *
 * Searching or filtering switches to a grid. A shelf is for browsing when you
 * do not know what you want; a grid is for scanning results when you do, and
 * showing both at once would be two answers to one question.
 */

/**
 * How many fits the shelf of ideas sits behind.
 *
 * Four, so it arrives while somebody is already scrolling rather than
 * being the thing they have to get past to reach the board. Counted in
 * tiles, not rows, because the masonry decides how tall a row is.
 */
const IDEAS_AFTER = 4;

/**
 * One cell of the board: a fit, or the shelf of ideas.
 *
 * A union rather than two lists, because the shelf is laid out *by*
 * the masonry - it takes a column slot like any tile, which is what
 * keeps it part of the wall instead of a band across it.
 */
type Row =
  | { kind: 'fit'; fit: FeedFit }
  | { kind: 'ideas'; doors: readonly Door[] };

export default function DiscoverScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const [group, setGroup] = useState('all');
  const [shared, setShared] = useState<FeedFit | null>(null);
  const [creating, setCreating] = useState(false);
  const [acting, setActing] = useState<PinSubject | null>(null);

  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const board = useBoard(group, signedIn);
  // The wheel stops when the grid is back. The shelves and
  // counters under it still reload, they just do not hold it
  // open after the pins have visibly repainted.
  const refresh = usePullToRefresh(undefined, {
    primary: () => board.refetch(),
  });
  // **A new grid when you come back to the app, and not before.**
  //
  // The board deliberately does not refetch on mount, so returning
  // from a pin finds the pins you left. Leaving the app and coming
  // back is the other thing people mean by "show me something new",
  // and it is a genuine background-to-active transition rather than
  // any focus event - a dismissed alert must not reshuffle the grid.
  useReturnedToApp(() => {
    if (signedIn) void board.refetch();
  });
  const groups = useFeedGroups(signedIn);
  const save = useSaveFit();

  // A screenshot of the board is somebody trying to keep one of these
  // pictures. The top fit is the best guess at which, and the sheet
  // says what it is offering rather than assuming.
  useScreenshotPrompt(() => {
    const first = board.data?.[0];
    if (first) setShared(first);
  });

  /**
   * Pin: pick a photograph, then compose around it.
   *
   * The library, never the camera. A fit is a picture somebody
   * already took and chose; opening the camera would be asking them
   * to produce one on the spot, which is not what a `+` on a board
   * means.
   */
  const pickAndCompose = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Photo access needed',
        'Grant access in Settings to post a picture. Everything else keeps working.',
      );
      return;
    }
    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.9,
    });
    if (picked.canceled || !picked.assets[0]) return;
    router.push({
      pathname: '/compose',
      params: { photo: picked.assets[0].uri },
    });
  };

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.two;
  const ideas = useIdeas(signedIn);

  /**
   * The board, with the shelf of ideas dropped into it.
   *
   * **After the fourth fit, not at the top.** A shelf above the board
   * is a thing to scroll past before reaching what you opened the tab
   * for; a few rows down it arrives while somebody is already looking.
   *
   * Only on the unfiltered board: inside a group, the reader has
   * already said what they want and a shelf suggesting other things is
   * an interruption, not a help.
   */
  // **The board waits for both.** The two queries settle
  // independently, and inserting the shelf into a list somebody is
  // already reading moves everything below the insertion point - a
  // shelf landing a moment after the board shunts the whole masonry
  // down mid-scroll. Drawing nothing until both are in means one
  // layout, with the shelf already in its place.
  //
  // It costs almost nothing: the two go out in parallel, so the wait
  // is the slower of them rather than the sum.
  const settling = board.isPending || ideas.isPending;

  const rows = useMemo<Row[]>(() => {
    if (settling) return [];
    // Read inside the callback rather than from an outer `?? []`: a
    // fresh empty array each render would rebuild the board every time.
    const tiles: Row[] = (board.data ?? []).map((fit) => ({
      kind: 'fit',
      fit,
    }));
    const shelf = ideas.data ?? [];
    if (group !== 'all' || shelf.length === 0 || tiles.length < IDEAS_AFTER) {
      return tiles;
    }
    return [
      ...tiles.slice(0, IDEAS_AFTER),
      { kind: 'ideas', doors: shelf },
      ...tiles.slice(IDEAS_AFTER),
    ];
  }, [settling, board.data, ideas.data, group]);

  /**
   * The chips: everything, then whatever is actually moving.
   *
   * Built from the server's own counts rather than a fixed list, so a
   * chip can never promise a group the board cannot then fill. A group
   * with posts but below the trending floor still appears — it is real,
   * it is just not claimed to be moving.
   */
  const chips = useMemo(
    () => [
      { id: 'all', label: 'All', trending: false },
      ...(groups.data ?? []).map((entry: { group: string; trending: boolean }) => ({
        id: entry.group,
        label: entry.group[0].toUpperCase() + entry.group.slice(1),
        trending: entry.trending,
      })),
    ],
    [groups.data],
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View
        style={{
          paddingTop: insets.top + Spacing.two,
          paddingHorizontal: Spacing.three,
          paddingBottom: Spacing.two,
          gap: Spacing.three,
        }}>
        {/* The masthead.

            The name comes from `branding.config.js` like every other
            user-facing name in this app, so a rename is a config change
            and never a code change. */}
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.two,
          }}>
          <ThemedText
            accessibilityRole="header"
            numberOfLines={1}
            style={{ ...labelType(28, 800), lineHeight: 34, flex: 1 }}>
            {BRAND.name}
          </ThemedText>

          {/* Make something. On the board it lands on, which is
              where somebody is when they think of it.

              A sheet rather than a route, because choosing between a
              pin, a collage and a board is a half-second decision and
              putting a screen in front of it is a navigation step
              before every post. */}
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Create"
            animateEntrance={false}
            scale={0.9}
            hitSlop={6}
            onPress={() => {
              void tapFeedback();
              setCreating(true);
            }}
            style={{
              width: TapTarget,
              height: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
            }}>
            <SymbolView
              name={{ ios: 'plus', android: 'add', web: 'add' }}
              size={24}
              tintColor={colors.text}
            />
          </MotionPressable>

          <InboxButton />
        </View>

        <SearchBar group={group} onGroup={setGroup} chips={chips} />
      </View>

      {/*
        A staggered board of photographs people took.

        FlashList's own masonry rather than a hand-rolled two-column
        split, so recycling still works on a long board — a manual split
        holds every cell mounted and is why hand-made masonry stutters.
      */}
      <FlashList
        // A screen and a half of pre-render rather than the default
        // quarter-screen. On a board of photographs the cells that
        // have not been rendered yet are the blank boxes that flick
        // past during a fast scroll, and they are what reads as the
        // list glitching.
        drawDistance={height}
        data={rows}
        masonry
        keyExtractor={(item) =>
          item.kind === 'fit' ? item.fit.id : 'ideas-shelf'
        }
        // Without this the list recycles a photograph's view for the
        // shelf and measures the wrong height, which moves the column
        // under the thumb.
        getItemType={(item) => item.kind}
        numColumns={columns}
        contentContainerStyle={{
          paddingHorizontal: Spacing.three - gutter / 2,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        }}
        showsVerticalScrollIndicator={false}
        // The shared control, not a second one written here.
        //
        // This board had its own, with `tintColor` only - which is
        // iOS-only, so Android drew its stock blue wheel, and iOS
        // drew a grey one that was easy to miss. The shared one is
        // branded, works on both, and refetches whatever this screen
        // is subscribed to rather than the two queries somebody
        // remembered to name.
        refreshControl={refresh.control}
        renderItem={({ item }: { item: Row }) =>
          item.kind === 'ideas' ? (
            <View style={{ paddingHorizontal: gutter / 2 }}>
              <IdeasShelf doors={item.doors} />
            </View>
          ) : (
          <View style={{ paddingHorizontal: gutter / 2, paddingBottom: gutter }}>
            <FitCard
              fit={item.fit}
              onOpen={() =>
                router.push({
                  pathname: '/fit/[id]',
                  params: { id: item.fit.id },
                })
              }
              // Only here. A board of strangers' fits is where keeping,
              // pinning and hiding one get decided; a shelf of your own
              // saves is a shelf of pictures you already chose.
              onMore={() =>
                setActing({
                  postId: item.fit.id,
                  title: item.fit.caption ?? `${item.fit.authorName}'s fit`,
                  coverAssetId: item.fit.mediaAssetIds[0] ?? null,
                  authorId: item.fit.authorId,
                })
              }
            />
          </View>
          )
        }
        ListEmptyComponent={
          settling ? (
            // Shaped like the board, not like a grid. Six identical 3:4
            // cells were a different shape from the masonry that
            // replaced them, so every tile moved the moment it arrived.
            <View style={{ paddingHorizontal: gutter / 2 }}>
              <SkeletonMasonry
                count={8}
                columns={columns}
                gutter={gutter}
                label="Loading the board"
              />
            </View>
          ) : (
            <EmptyState
              status="empty"
              title={group === 'all' ? 'Nothing posted yet' : 'Nothing in that group'}
              body={
                group === 'all'
                  ? 'Discover fills up as people share what they wore. Be the first.'
                  : 'No fits tagged that way in the last couple of months. The other groups have plenty.'
              }
              action={{
                label: group === 'all' ? 'Share a fit' : 'Show everything',
                onPress: () => {
                  void tapFeedback();
                  if (group === 'all') router.push('/compose');
                  else setGroup('all');
                },
              }}
            />
          )
        }
      />

      {/* Pin goes straight to the camera roll: a pin *is* a
          photograph, so the first question is which picture rather
          than which of our looks. The composer opens after, with it
          already attached. */}
      {/* Everything one fit can do, from the board. The sheet acts
          on the fit itself: boards hold published fits, and the avatar
          and the stylist take it as a photograph. */}
      <PinActions
        subject={acting}
        visible={acting !== null}
        onClose={() => setActing(null)}
      />

      <CreateSheet
        visible={creating}
        onClose={() => setCreating(false)}
        onPin={() => void pickAndCompose()}
      />

      <ShareSheet
        fit={shared}
        visible={shared !== null}
        reason="screenshot"
        onClose={() => setShared(null)}
        onSave={() => shared && save.mutate({ id: shared.id, saved: true })}
        // Both act on the fit that was screenshotted, not on whatever
        // curated look it happened to be tagged with. Boards hold
        // published fits, and the avatar is dressed from the
        // photograph rather than from a catalogue entry.
        onBoard={() => {
          if (!shared) return;
          setActing({
            postId: shared.id,
            title: shared.caption ?? `${shared.authorName}'s fit`,
            coverAssetId: shared.mediaAssetIds[0] ?? null,
            authorId: shared.authorId,
          });
          setShared(null);
        }}
        onTryOn={() => {
          if (!shared) return;
          // **The figure first, and no bill for it.**
          //
          // This fired a paid render the moment the row was tapped,
          // before anybody had seen anything - so "try it on" cost
          // money and thirty seconds whether or not the result was
          // wanted. Carrying the fit instead lets the avatar screen
          // cut that fit's garments out of the photograph and dress
          // the mannequin with them, which is instant, free and the
          // actual clothes. The photorealistic render is a button
          // there, for somebody who asks for it.
          const id = shared.id;
          setShared(null);
          router.push({ pathname: '/avatar', params: { fit: id } });
        }}
      />
    </View>
  );
}

/**
 * The groups above the board.
 *
 * **No search field.** Searching is its own screen, reached from the
 * tab bar, and a second live input here would be a second place to
 * type the same thing. What belongs at the top of Discover is the one
 * control that changes what is under it.
 *
 * A dot marks a group the server reports as moving. The label alone
 * cannot say that, and a word like "trending" on nine chips says
 * nothing at all.
 */
function SearchBar({
  group,
  onGroup,
  chips,
}: {
  group: string;
  onGroup: (next: string) => void;
  chips: readonly { id: string; label: string; trending: boolean }[];
}) {
  const colors = Colors[useScheme()];

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ flexDirection: 'row', gap: Spacing.four }}>
      {chips.map((option) => {
        const active = option.id === group;
        return (
          <Pressable
            key={option.id}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={
              option.trending ? `${option.label}, trending` : option.label
            }
            onPress={() => {
              void tapFeedback();
              onGroup(option.id);
            }}
            hitSlop={6}
            style={({ pressed }) => ({
              minHeight: 40,
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.one,
              // A rule under the word, not a box around it. Six pills
              // over a board of photographs is six boxes competing
              // with the pictures; an underline says the same thing
              // and draws nothing on the options you are not on.
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
            {option.trending ? (
              <View
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: Radius.full,
                  backgroundColor: colors.accent,
                }}
              />
            ) : null}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
