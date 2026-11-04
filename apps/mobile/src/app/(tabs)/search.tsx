import { FlashList } from '@shopify/flash-list';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef, useState, type ComponentRef } from 'react';
import {
  Alert,
  ScrollView,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  prefetchMember,
  seedMember,
  type FoundPerson,
  usePeopleSearch,
  useSetFollowing,
} from '@/api/queries/community';
import { useBoard } from '@/api/queries/discover-feed';
import { useExplore, type Door } from '@/api/queries/explore';
import { useMoodboards } from '@/api/queries/moodboards';
import { useMe } from '@/api/queries/me';
import { usePostImages } from '@/api/queries/post-media';
import { isOwnPage } from '@/features/profile/whose-page';
import { Refine, refinements } from '@/features/search/refine';
import { MIN_SUGGEST, useTagFeed, useTagSuggestions } from '@/api/queries/tags';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { Skeleton, SkeletonMasonry, SkeletonRows } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { FitCard } from '@/features/feed/fit-card';
import {
  NO_FILTER,
  SearchFilterSheet,
  filtered,
  type SearchFilter,
} from '@/features/feed/search-filter';
import { PictureResults } from '@/features/feed/picture-results';
import { Scanning } from '@/features/feed/scanning';
import {
  searchByPicture,
  type VisualResult,
} from '@/features/feed/visual-search';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { useScheme } from '@/hooks/use-theme';

/**
 * Search: browse, type, then look.
 *
 * **Three states, one screen.** With nothing typed it is a place to
 * browse, because a search screen that shows a blank page until
 * somebody types only helps people who already know the word they
 * want. While typing it offers the app's own hashtags. Once a search
 * is run it is a board of results. Each state is the whole screen
 * rather than a strip of one, so there is never a half-committed page
 * that is partly suggestions and partly results.
 *
 * **Suggestions are the app's own vocabulary.** Every row has fits
 * behind it, so a tap cannot land on the empty state — which is the
 * worst thing a suggestion can do and the usual thing a guessed one
 * does.
 *
 * **Looks and people are a filter, not a pair of tabs.** Two tabs over
 * a result list make somebody choose before they have seen anything;
 * the filter sits behind one control and defaults to fits, which is
 * what this app is for.
 *
 * **The camera photographs a garment into the wardrobe**, where the
 * stylist can use it — rather than "find me this picture", which is
 * what the same button means on a board app.
 */
export default function SearchScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const field = useRef<ComponentRef<typeof TextInput>>(null);

  const [query, setQuery] = useState('');
  /** The search actually being shown. Null while browsing or typing. */
  const [run, setRun] = useState<string | null>(null);
  const [filter, setFilter] = useState<SearchFilter>(NO_FILTER);
  const [filtering, setFiltering] = useState(false);
  const [reading, setReading] = useState(false);
  /** Their photograph, shown under the scanner while it is read. */
  const [scanning, setScanning] = useState<string | null>(null);
  /** What the camera found, once it has. */
  const [found, setFound] = useState<VisualResult | null>(null);

  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const capture = useGarmentCapture();
  const refresh = usePullToRefresh();

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.two;
  const column = (width - Spacing.three * 2 - gutter) / columns;

  const typing = run === null && query.trim().length > 0;
  const suggestions = useTagSuggestions(query, signedIn && typing);

  const tagged = useTagFeed(
    run ?? '',
    signedIn && run !== null && filter.kind === 'fits',
    filter.photographsOnly,
  );
  // Asked for on every search, not only under the People filter.
  //
  // Typing somebody's name and getting a grid of hashtagged
  // photographs is the app saying "no such person" when the person is
  // right there - and nobody thinks to change a filter first, because
  // they have already told the app what they are looking for.
  const people = usePeopleSearch(run ?? '', signedIn && run !== null);
  const boards = useMoodboards(signedIn && run !== null && filter.kind === 'boards');
  const follow = useSetFollowing();
  // So your own row in the results does not offer to follow you.
  const me = useMe(signedIn);

  // **Whether the search as a whole found nothing**, which is not the
  // same question as whether the grid of fits is empty. People and
  // boards are searched alongside the tags and drawn above the grid,
  // so answering on the fits alone announced "nothing here" over
  // results that were on screen.
  const foundNothingAnywhere =
    (tagged.data?.fits ?? []).length === 0 &&
    (people.data ?? []).length === 0 &&
    (boards.data ?? []).length === 0;

  // Fetched for the browse screen as before, and now also when a
  // search found nothing: that is precisely when its busy list is
  // needed, and it was the one state it was switched off for.
  const explore = useExplore(signedIn && (run === null || foundNothingAnywhere));

  // **Something to look at when the search found nothing.**
  //
  // The reference answers even nonsense with a page of pictures and
  // a way to refine, never a blank screen with the word "nothing" on
  // it - and a dead end is the one thing a search must not be. This
  // is the same board the Discover tab shows, so it is almost always
  // already in cache and costs no request.
  //
  // It is drawn *below* the empty state, which says in as many words
  // that nothing matched. Nothing here claims to be a result.
  const instead = useBoard('all', signedIn && foundNothingAnywhere);
  const forYou = explore.data?.forYou ?? [];
  const popular = explore.data?.popular ?? [];

  // What to offer instead. Related tags first because they answer
  // this search; the busy list behind them because a query that
  // matched nothing has no related anything, and that is exactly the
  // case this exists for.
  const refineWith = refinements({
    related: tagged.data?.related,
    popular: [...popular, ...forYou],
    exclude: run ?? undefined,
  });

  const matchingBoards = useMemo(() => {
    const needle = (run ?? '').trim().toLowerCase();
    return (boards.data ?? []).filter((board) =>
      board.name.toLowerCase().includes(needle),
    );
  }, [boards.data, run]);

  const search = (term: string) => {
    const cleaned = term.trim().replace(/^#/, '');
    if (!cleaned) return;
    setQuery(cleaned);
    setRun(cleaned);
    field.current?.blur();
  };

  const cancel = () => {
    setQuery('');
    setRun(null);
    field.current?.blur();
  };

  /**
   * Search by picture.
   *
   * Reading a photograph takes five to nine seconds, which is slow for
   * a search and is the real cost of it. The button says what is
   * happening for the whole wait rather than spinning.
   */
  const photograph = async () => {
    const result = await capture.photograph();
    if (result === 'denied') {
      Alert.alert(
        'Camera access needed',
        'Grant access in Settings to search with a picture. Everything else keeps working.',
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
    const shot = result[0];
    if (!shot) return;

    // **The wait goes over their photograph, not on a button.**
    //
    // Reading costs five to nine seconds, and the old version spent
    // it with the camera closed and a button reading "Reading" on an
    // otherwise unchanged screen. Somebody who has just framed a
    // shot is looking at their picture.
    setScanning(shot.uri);
    setReading(true);
    try {
      const found = await searchByPicture(shot.uri);
      void successFeedback();
      // **The results, in a sheet, rather than a jump or an alert.**
      //
      // This used to take the strongest tag and navigate to its
      // page - losing the photograph and every other reading - and
      // when no tag matched it showed "Nothing to go on" and left
      // the person exactly where they started. The sheet shows what
      // was found, including the nearest things when nothing was
      // tagged, and says which is which.
      setFound(found);
    } catch (caught) {
      Alert.alert(
        'Could not search that',
        caught instanceof Error ? caught.message : 'Try again in a moment.',
      );
    } finally {
      setReading(false);
      setScanning(null);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View
        style={{
          paddingTop: insets.top + Spacing.two,
          paddingHorizontal: Spacing.three,
          paddingBottom: Spacing.two,
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
        }}>
        {run !== null ? (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Back to browsing"
            animateEntrance={false}
            scale={0.92}
            hitSlop={8}
            onPress={() => {
              void tapFeedback();
              cancel();
            }}
            style={{
              width: TapTarget - Spacing.two,
              height: TapTarget,
              alignItems: 'flex-start',
              justifyContent: 'center',
            }}>
            <SymbolView
              name={{
                ios: 'chevron.left',
                android: 'arrow_back',
                web: 'arrow_back',
              }}
              size={20}
              tintColor={colors.text}
            />
          </MotionPressable>
        ) : null}

        {/* One field, whatever the screen is doing. The glyph inside
            it is the search affordance; the camera on the right is a
            different search and sits outside the capsule it is not
            part of. */}
        <View
          style={{
            flex: 1,
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.two,
            minHeight: TapTarget + Spacing.one,
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.full,
            borderWidth: 1,
            borderColor: colors.borderStrong,
          }}>
          {run === null && !typing ? (
            <SymbolView
              name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }}
              size={18}
              tintColor={colors.textSecondary}
            />
          ) : null}
          <TextInput
            ref={field}
            value={query}
            onChangeText={(next) => {
              setQuery(next);
              // Editing after a search puts the screen back into
              // choosing, rather than leaving stale results under a
              // field that no longer describes them.
              if (run !== null) setRun(null);
            }}
            onSubmitEditing={() => search(query)}
            placeholder="Search fits, tags and people"
            placeholderTextColor={colors.textSecondary}
            accessibilityLabel="Search"
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="search"
            clearButtonMode="never"
            style={{
              flex: 1,
              paddingVertical: Spacing.two,
              color: colors.text,
              ...labelType(FontSize.body, 400),
            }}
          />
          {query.length > 0 ? (
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel="Clear the search"
              animateEntrance={false}
              scale={0.9}
              hitSlop={10}
              onPress={() => {
                void tapFeedback();
                setQuery('');
                setRun(null);
                field.current?.focus();
              }}>
              <SymbolView
                name={{
                  ios: 'xmark.circle.fill',
                  android: 'cancel',
                  web: 'cancel',
                }}
                size={18}
                tintColor={colors.textSecondary}
              />
            </MotionPressable>
          ) : null}
        </View>

        {run !== null ? (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Filter these results"
            accessibilityState={{ selected: filtered(filter) }}
            animateEntrance={false}
            scale={0.92}
            hitSlop={8}
            onPress={() => {
              void tapFeedback();
              setFiltering(true);
            }}
            style={{
              width: TapTarget - Spacing.two,
              height: TapTarget,
              alignItems: 'flex-end',
              justifyContent: 'center',
            }}>
            <SymbolView
              name={{
                ios: 'line.3.horizontal.decrease',
                android: 'tune',
                web: 'tune',
              }}
              size={20}
              tintColor={filtered(filter) ? colors.accent : colors.text}
            />
          </MotionPressable>
        ) : typing ? (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Cancel"
            animateEntrance={false}
            scale={0.96}
            onPress={() => {
              void tapFeedback();
              cancel();
            }}
            style={{ minHeight: TapTarget, justifyContent: 'center' }}>
            <ThemedText style={labelType(FontSize.body, 400)}>Cancel</ThemedText>
          </MotionPressable>
        ) : (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Search with a picture"
            accessibilityHint="Reads the clothes in a photo and finds fits like it"
            accessibilityState={{ busy: reading, disabled: reading }}
            disabled={reading}
            animateEntrance={false}
            scale={0.92}
            onPress={() => {
              void tapFeedback();
              void photograph();
            }}
            style={{
              width: TapTarget - Spacing.two,
              height: TapTarget,
              alignItems: 'flex-end',
              justifyContent: 'center',
              opacity: reading ? 0.5 : 1,
            }}>
            <SymbolView
              name={{
                ios: reading ? 'hourglass' : 'camera',
                android: reading ? 'hourglass_empty' : 'photo_camera',
                web: 'photo_camera',
              }}
              size={22}
              tintColor={colors.text}
            />
          </MotionPressable>
        )}
      </View>

      {typing ? (
        <Suggestions
          typed={query}
          tags={suggestions.data ?? []}
          loading={suggestions.isPending}
          onPick={search}
        />
      ) : run !== null ? (
        filter.kind === 'people' ? (
          <People
            query={run}
            people={people.data ?? []}
            loading={people.isPending}
            meId={me.data?.userId}
            onFollow={(person) =>
              follow.mutate({ userId: person.userId, follow: !person.followed })
            }
          />
        ) : filter.kind === 'boards' ? (
          <Boards query={run} boards={matchingBoards} loading={boards.isPending} />
        ) : (
          <FlashList
        // A screen and a half of pre-render rather than the default
        // quarter-screen. On a board of photographs the cells that
        // have not been rendered yet are the blank boxes that flick
        // past during a fast scroll, and they are what reads as the
        // list glitching.
        drawDistance={height}
            data={foundNothingAnywhere ? (instead.data ?? []) : (tagged.data?.fits ?? [])}
            masonry
            keyExtractor={(item) => item.id}
            numColumns={columns}
            keyboardShouldPersistTaps="handled"
            refreshControl={refresh.control}
            contentContainerStyle={{
              paddingHorizontal: Spacing.three - gutter / 2,
              paddingBottom: insets.bottom + Spacing.five,
            }}
            showsVerticalScrollIndicator={false}
            ListHeaderComponent={
              <>
                {/* Anybody of that name, above the looks.

                    A few, not the lot: this is the answer to "is she
                    on here", and somebody scanning a longer list
                    wanted the People filter, which is still there. */}
                {(people.data ?? []).length > 0 ? (
                  <PeopleStrip
                    people={(people.data ?? []).slice(0, PEOPLE_IN_RESULTS)}
                    total={(people.data ?? []).length}
                    onSeeAll={() => setFilter({ ...filter, kind: 'people' })}
                  />
                ) : null}
                {(tagged.data?.related ?? []).length > 0 ? (
                  <Related
                    tags={tagged.data?.related ?? []}
                    gutter={gutter}
                    onPick={search}
                  />
                ) : null}
                {/* **In the header, not the empty slot.** There are
                    rows under this now - the board, so the screen is
                    never a blank page with the word "nothing" on it -
                    and a list with rows never draws its empty
                    component. The message has to sit above them, and
                    it is what makes clear that what follows is not a
                    set of results. */}
                {foundNothingAnywhere && !tagged.isPending ? (
                  <View style={{ gap: Spacing.three, paddingBottom: Spacing.three }}>
                    <EmptyState
                      status="empty"
                      title={`No results for "${run}"`}
                      body={
                        filter.photographsOnly
                          ? 'Turning the photographs filter off widens it.'
                          : 'Try one of these.'
                      }
                    />
                    <Refine doors={refineWith} onPick={search} />
                  </View>
                ) : null}
              </>
            }
            renderItem={({ item }) => (
              <View
                style={{ paddingHorizontal: gutter / 2, paddingBottom: gutter }}>
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
              tagged.isPending ? (
                // Shaped like the results, so nothing moves when they
                // land. One grey rectangle then a masonry of real
                // heights is the jump this replaces.
                <SkeletonMasonry
                  count={6}
                  columns={columns}
                  gutter={gutter}
                  label="Searching"
                />
              ) : null
              // Everything a failed search has to say is in the
              // header now, because the list has rows under it and a
              // list with rows never draws this.
            }
          />
        )
      ) : (
        <ScrollView
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          refreshControl={refresh.control}
          contentContainerStyle={{
            paddingHorizontal: Spacing.three - gutter / 2,
            paddingBottom: insets.bottom + Spacing.five,
            gap: Spacing.five,
          }}>
          {explore.isPending ? (
            <View style={{ gap: Spacing.two }}>
              <Skeleton width="100%" height={96} radius={Radius.md} />
              <Skeleton width="100%" height={96} radius={Radius.md} />
            </View>
          ) : (
            <>
              {forYou.length > 0 ? (
                <Doors title="Ideas for you" doors={forYou} />
              ) : null}
              {popular.length > 0 ? (
                <Doors title="Popular now" doors={popular} />
              ) : null}
              {forYou.length === 0 && popular.length === 0 ? (
                <EmptyState
                  status="empty"
                  title="Nothing to browse yet"
                  body="Once people start posting fits, the hashtags they use show up here."
                />
              ) : null}
            </>
          )}
        </ScrollView>
      )}

      <SearchFilterSheet
        visible={filtering}
        filter={filter}
        onClose={() => setFiltering(false)}
        onApply={(next) => {
          setFilter(next);
          setFiltering(false);
        }}
      />

      {/* **The wait, over their own photograph.**

          Mounted only while the read runs, so it starts at its
          first line by being new rather than by resetting state in
          an effect. */}
      {scanning ? <Scanning uri={scanning} /> : null}

      {/* What it found, as a sheet over this screen. Dismissing it
          leaves the query and the board exactly as they were. */}
      <PictureResults result={found} onClose={() => setFound(null)} />

    </View>
  );
}

/**
 * What the field offers while somebody is still typing.
 *
 * **The typed part stays quiet and the rest is bold.** It is the one
 * treatment that makes a list of near-identical strings scannable: the
 * eye reads only what it has not typed yet.
 */
function Suggestions({
  typed,
  tags,
  loading,
  onPick,
}: {
  typed: string;
  tags: readonly { tag: string; posts: number }[];
  loading: boolean;
  onPick: (tag: string) => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const needle = typed.trim().replace(/^#/, '').toLowerCase();

  if (needle.length < MIN_SUGGEST) {
    return (
      <View style={{ paddingHorizontal: Spacing.three, paddingTop: Spacing.two }}>
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.subhead, 400)}>
          Keep typing. One letter matches almost everything.
        </ThemedText>
      </View>
    );
  }
  if (loading) {
    return (
      <View style={{ padding: Spacing.three, gap: Spacing.three }}>
        <SkeletonRows count={5} label="Searching for people" />
      </View>
    );
  }
  if (tags.length === 0) {
    return (
      <View style={{ paddingHorizontal: Spacing.three, paddingTop: Spacing.two }}>
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.subhead, 400)}>
          Nothing here is tagged with that. Press search anyway to be sure.
        </ThemedText>
      </View>
    );
  }

  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{ paddingBottom: insets.bottom + Spacing.five }}>
      {tags.map((item) => {
        const at = item.tag.indexOf(needle);
        const before = at < 0 ? '' : item.tag.slice(0, at);
        const hit = at < 0 ? '' : item.tag.slice(at, at + needle.length);
        const after = at < 0 ? item.tag : item.tag.slice(at + needle.length);
        return (
          <MotionPressable
            key={item.tag}
            accessibilityRole="link"
            accessibilityLabel={`${item.tag}, ${
              item.posts === 1 ? '1 fit' : `${item.posts} fits`
            }`}
            animateEntrance={false}
            scale={0.99}
            onPress={() => {
              void tapFeedback();
              onPick(item.tag);
            }}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
              minHeight: TapTarget + Spacing.two,
              paddingHorizontal: Spacing.three,
            }}>
            <SymbolView
              name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }}
              size={20}
              tintColor={colors.text}
            />
            <ThemedText numberOfLines={1} style={{ flex: 1 }}>
              <ThemedText
                themeColor="textSecondary"
                style={labelType(FontSize.title3, 400)}>
                {before}
                {hit}
              </ThemedText>
              <ThemedText style={labelType(FontSize.title3, 800)}>
                {after}
              </ThemedText>
            </ThemedText>
          </MotionPressable>
        );
      })}
    </ScrollView>
  );
}

/** Tags that travel with this one, across the top of the results. */
function Related({
  tags,
  gutter,
  onPick,
}: {
  tags: readonly string[];
  gutter: number;
  onPick: (tag: string) => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{
        gap: Spacing.one,
        paddingHorizontal: gutter / 2,
        paddingBottom: Spacing.two,
      }}>
      {tags.map((tag) => (
        <MotionPressable
          key={tag}
          accessibilityRole="link"
          accessibilityLabel={`Fits tagged ${tag}`}
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            onPick(tag);
          }}
          style={{
            minHeight: 40,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
          }}>
          <ThemedText style={labelType(FontSize.subhead, 800)}>{tag}</ThemedText>
        </MotionPressable>
      ))}
    </ScrollView>
  );
}

/**
 * A shelf of doors: two columns of wide tiles, each a hashtag.
 *
 * **Real photographs, not cover art.** Each tile wears the best fit
 * actually under that tag, chosen by the same score the board ranks
 * by. This is the one place in the app where type sits *on* a picture:
 * these are labels first, which is the opposite of a pin and takes the
 * opposite treatment.
 */
function Doors({ title, doors }: { title: string; doors: readonly Door[] }) {
  const colors = Colors[useScheme()];
  const images = usePostImages(
    doors.map((door) => door.coverAssetId).filter(Boolean) as string[],
  );

  return (
    <View style={{ gap: Spacing.two }}>
      {/* Centred, in the grotesque: these are signposts over two
          shelves of the same thing, not chapter titles. */}
      <ThemedText
        accessibilityRole="header"
        style={{
          ...labelType(FontSize.body, 800),
          lineHeight: 22,
          textAlign: 'center',
        }}>
        {title}
      </ThemedText>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
        {doors.map((door, index) => {
          const uri = door.coverAssetId
            ? (images.data?.[door.coverAssetId] ?? null)
            : null;
          return (
            <MotionPressable
              key={door.key}
              // No entrance. These sit in a scrolling shelf that is
              // re-rendered as the query changes, and an animation on
              // a tile that was already there reads as a glitch.
              animateEntrance={false}
              accessibilityRole="button"
              accessibilityLabel={`${door.label}, ${
                door.posts === 1 ? '1 fit' : `${door.posts} fits`
              }`}
              onPress={() => {
                void tapFeedback();
                router.push({ pathname: '/tag/[tag]', params: { tag: door.key } });
              }}
              style={{
                // Two per row, with the gap taken out of the pair.
                width: '50%',
                flexGrow: 1,
                flexBasis: 0,
                minWidth: 140,
                height: 96,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                overflow: 'hidden',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: colors.backgroundElement,
              }}>
              {uri ? (
                <Image
                  source={{ uri }}
                  contentFit="cover"
                  transition={ImageFade}
                  style={{ position: 'absolute', width: '100%', height: '100%' }}
                />
              ) : null}
              {/* A flat wash, not a gradient: the label is centred, so
                  there is no single side to darken. */}
              <View
                style={{
                  position: 'absolute',
                  width: '100%',
                  height: '100%',
                  backgroundColor: '#00000059',
                }}
              />
              <ThemedText
                numberOfLines={2}
                style={{
                  ...labelType(FontSize.body, 800),
                  color: '#FFFFFF',
                  textAlign: 'center',
                  paddingHorizontal: Spacing.two,
                }}>
                {door.label}
              </ThemedText>
            </MotionPressable>
          );
        })}
      </View>
    </View>
  );
}

/** Your own boards, by name. Boards are private, so these are yours. */
function Boards({
  query,
  boards,
  loading,
}: {
  query: string;
  boards: readonly { id: string; name: string; postIds: readonly string[] }[];
  loading: boolean;
}) {
  const insets = useSafeAreaInsets();
  if (loading) {
    return (
      <View style={{ padding: Spacing.three, gap: Spacing.three }}>
        <SkeletonRows count={3} avatar={false} label="Searching your boards" />
      </View>
    );
  }
  if (boards.length === 0) {
    return (
      <EmptyState
        status="empty"
        title="No board by that name"
        body={`None of your boards match "${query}". Boards are private, so this searches your own.`}
      />
    );
  }
  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{
        paddingHorizontal: Spacing.three,
        paddingBottom: insets.bottom + Spacing.five,
      }}>
      {boards.map((board) => (
        <MotionPressable
          key={board.id}
          accessibilityRole="link"
          accessibilityLabel={`${board.name}, ${
            board.postIds.length === 1 ? '1 pin' : `${board.postIds.length} pins`
          }`}
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            router.push({ pathname: '/board/[id]', params: { id: board.id } });
          }}
          style={{
            minHeight: TapTarget + Spacing.two,
            justifyContent: 'center',
            gap: Spacing.half,
          }}>
          <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={1}>
            {board.name}
          </ThemedText>
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.footnote, 400)}>
            {board.postIds.length === 1
              ? '1 pin'
              : `${board.postIds.length} pins`}
          </ThemedText>
        </MotionPressable>
      ))}
    </ScrollView>
  );
}

/** How many names sit above the looks before it is a list, not an answer. */
const PEOPLE_IN_RESULTS = 3;

/**
 * Anybody of that name, above the pictures.
 *
 * **Searching a name used to return photographs.** People were
 * behind a filter nobody switched to, because they had already said
 * what they were looking for by typing it. This is the answer in
 * place: a few names, and a way to the full list.
 */
function PeopleStrip({
  people,
  total,
  onSeeAll,
}: {
  people: readonly FoundPerson[];
  total: number;
  onSeeAll: () => void;
}) {
  const colors = Colors[useScheme()];
  const queries = useQueryClient();

  return (
    <View style={{ paddingHorizontal: Spacing.one, paddingBottom: Spacing.three }}>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          paddingBottom: Spacing.two,
        }}>
        <ThemedText accessibilityRole="header" style={labelType(FontSize.meta, 800)}>
          People
        </ThemedText>
        <View style={{ flex: 1 }} />
        {total > people.length ? (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={`See all ${total} people`}
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              onSeeAll();
            }}>
            <ThemedText type="smallBold" style={{ color: colors.accent }}>
              See all {total}
            </ThemedText>
          </MotionPressable>
        ) : null}
      </View>

      <View style={{ gap: Spacing.two }}>
        {people.map((person) => (
          <MotionPressable
            key={person.userId}
            accessibilityRole="button"
            accessibilityLabel={`${person.name}. ${person.fits} ${
              person.fits === 1 ? 'fit' : 'fits'
            }.`}
            accessibilityHint="Opens their page"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              seedMember(queries, {
                userId: person.userId,
                name: person.name,
              });
              prefetchMember(queries, person.userId);
              router.push({
                pathname: '/member/[id]',
                params: { id: person.userId },
              });
            }}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
              minHeight: TapTarget,
            }}>
            <Monogram name={person.name} id={person.userId} size={40} />
            <View style={{ flex: 1, gap: Spacing.half }}>
              <ThemedText type="smallBold">{person.name}</ThemedText>
              <ThemedText type="small" themeColor="textSecondary">
                {person.fits === 0
                  ? 'No fits yet'
                  : `${person.fits} ${person.fits === 1 ? 'fit' : 'fits'}`}
              </ThemedText>
            </View>
          </MotionPressable>
        ))}
      </View>
    </View>
  );
}


/**
 * People matching the name typed above.
 *
 * **The empty state says why it is empty, and the reason is not
 * "nobody is called that".** Only people who have published a fit can
 * be found, so an empty result means either no match or a match who
 * has never posted — and telling somebody the first when the second is
 * true would have them concluding a friend is not on the app.
 */
function People({
  query,
  people,
  loading,
  onFollow,
  meId,
}: {
  query: string;
  people: readonly FoundPerson[];
  loading: boolean;
  onFollow: (person: FoundPerson) => void;
  /** The signed-in account, so its own row does not offer to follow it. */
  meId?: string | null;
}) {
  const colors = Colors[useScheme()];
  const queries = useQueryClient();
  const insets = useSafeAreaInsets();

  if (loading) {
    return (
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} height={TapTarget + Spacing.four} radius={Radius.md} />
        ))}
      </View>
    );
  }
  if (people.length === 0) {
    return (
      <EmptyState
        status="empty"
        title="Nobody here by that name"
        body={`No one called "${query}" is here. People are findable once they have set a name.`}
      />
    );
  }

  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{
        paddingHorizontal: Spacing.three,
        paddingBottom: insets.bottom + Spacing.five,
        gap: Spacing.two,
      }}>
      {people.map((person, index) => (
        <MotionPressable
          key={person.userId}
          index={index}
          accessibilityRole="button"
          accessibilityLabel={`${person.name}. ${person.fits} ${
            person.fits === 1 ? 'fit' : 'fits'
          }, ${person.followerCount} ${
            person.followerCount === 1 ? 'follower' : 'followers'
          }.`}
          accessibilityHint="Opens their page"
          onPress={() => {
            void tapFeedback();
            seedMember(queries, {
              userId: person.userId,
              name: person.name,
            });
            prefetchMember(queries, person.userId);
            router.push({ pathname: '/member/[id]', params: { id: person.userId } });
          }}
          style={{
            minHeight: TapTarget,
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.three,
            paddingVertical: Spacing.two,
          }}>
          {/* An initial, not a photograph: a face is the one thing a
              stranger's card could carry that identifies a real person
              by sight, and a name search is where that matters most. */}
          <Monogram name={person.name} id={person.userId} />
          <View style={{ flex: 1, gap: Spacing.half }}>
            <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={1}>
              {person.name}
            </ThemedText>
            <ThemedText
              themeColor="textSecondary"
              numberOfLines={1}
              style={labelType(FontSize.subhead, 400)}>
              {person.followerCount === 1
                ? '1 follower'
                : `${person.followerCount} followers`}
            </ThemedText>
          </View>
          {/* Your own account appears in these results on purpose -
              looking yourself up is how somebody checks what
              strangers can see of them. What it must not carry is a
              button to follow yourself, which the server refuses
              anyway. A plain word, so the gap is explained rather
              than just empty. */}
          {isOwnPage({ viewerId: meId, pageId: person.userId }) ? (
            <ThemedText
              themeColor="textSecondary"
              style={labelType(FontSize.subhead, 800)}>
              You
            </ThemedText>
          ) : (
          <MotionPressable
            accessibilityRole="button"
            accessibilityState={{ selected: person.followed }}
            accessibilityLabel={
              person.followed ? `Unfollow ${person.name}` : `Follow ${person.name}`
            }
            animateEntrance={false}
            scale={0.95}
            onPress={() => {
              void tapFeedback();
              onFollow(person);
            }}
            style={{
              minHeight: 40,
              justifyContent: 'center',
              paddingHorizontal: Spacing.four,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: person.followed
                ? colors.text
                : colors.backgroundElement,
            }}>
            <ThemedText
              style={{
                ...labelType(FontSize.subhead, 800),
                color: person.followed ? colors.background : colors.text,
              }}>
              {person.followed ? 'Following' : 'Follow'}
            </ThemedText>
          </MotionPressable>
          )}
        </MotionPressable>
      ))}
    </ScrollView>
  );
}
