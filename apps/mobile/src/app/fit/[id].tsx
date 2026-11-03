import { Image } from 'expo-image';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  View,
  useWindowDimensions,
} from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useFitDetail,
  useMoreUnder,
  useReact,
  useReactionKinds,
  useHideFit,
  useSaveFit,
} from '@/api/queries/discover-feed';
import { Comments } from '@/features/feed/comments';
import { ACTION_WIDTH, ActionIcon, FitAction } from '@/features/feed/fit-action';
import { heroFrame } from '@/features/feed/hero-frame';
import { clampShape } from '@/features/feed/shape';
import { shapeFor } from '@/features/feed/shapes';
import { FitMenu } from '@/features/feed/fit-menu';
import { usePostImages } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import {
  MotionPressable,
  tapFeedback,
} from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import { PinToBoard } from '@/components/ui/pin-to-board';
import { SavedNote } from '@/components/ui/saved-note';
import { Skeleton, SkeletonMasonry } from '@/components/ui/skeleton';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { Zoomable } from '@/features/feed/zoomable';
import { surroundOpacity } from '@/features/feed/zoom';
import { useImmersion } from '@/features/navigation/attention-context';
import {
  BottomTabInset,
  Colors,
  FontSize,
  ImageFade,
  Motion,
  Pop,
  PopFrom,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import {
  prefetchMember,
  seedMember,
} from '@/api/queries/community';
import { useAuth } from '@/features/auth/session';
import { intoColumns } from '@/features/feed/columns';
import {
  useDeletePost,
  useSetPostVisibility,
} from '@/api/queries/posts';
import { FitCard } from '@/features/feed/fit-card';
import { PhotoView } from '@/features/feed/photo-view';
import { openSite, safeSite } from '@/features/profile/website';
import { ReactionPicker } from '@/features/feed/reaction-picker';
import { ShareSheet, shareFit } from '@/features/feed/share-sheet';
import { useScreenshotPrompt } from '@/features/feed/use-screenshot';
import { useReducedMotion, useScheme } from '@/hooks/use-theme';

/**
 * One fit, full size, with who posted it and what to do about it.
 *
 * **The photograph is the page.** It runs edge to edge with only two
 * floating chips over it, because this is the screen somebody arrived
 * at to look at a picture — a header bar reserving its height above it
 * would spend the best part of the screen on a back button.
 *
 * **The actions are LUXish verbs, not a social tally.** Keeping, boards
 * and putting it on your own avatar are things this app can do with an
 * outfit; a comment count would be a number with nothing behind it,
 * since comments are not built.
 */
/**
 * The hero's shape.
 *
 * `until` is what it stands at before the picture has loaded, and
 * `tall` is the most of the screen one may take: past that, the
 * caption and every control would be below the fold on arrival, so a
 * very tall photograph is shown narrower rather than shorter.
 */
const HERO = { until: 3 / 4, tall: 0.82 } as const;


/** Tags shown before the rest go behind a `...`. About a line and a half. */
const SHOWN_TAGS = 6;

export default function FitDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colors = Colors[useScheme()];
  const queries = useQueryClient();
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  // The tab bar is mounted at the root and cannot see this scroll
  // view, so the posture travels through a context.
  const { onScroll, measureFocus, release } = useImmersion();

  /**
   * How far into the picture somebody has pinched.
   *
   * Shared rather than React state: the page behind the photograph
   * fades as the zoom goes in, and driving that from state would
   * mean a round trip to the JavaScript thread on every frame of a
   * pinch. The fade and the zoom are the same frame this way.
   */
  const zoom = useSharedValue(1);
  /**
   * Whether a pinch is in progress, which the scroll view needs.
   *
   * The one thing that has to cross to the JavaScript thread: a
   * dragged picture and a scrolling page are the same vertical
   * gesture, and without this the page scrolls out from under the
   * finger that is panning the photograph.
   */
  const [zooming, setZooming] = useState(false);

  /** The page behind the picture, getting out of its way. */
  const surround = useAnimatedStyle(() => ({
    opacity: surroundOpacity(zoom.value),
  }));

  // Leaving while immersed would take the bar with us: the next
  // screen is a list, nothing on it reports a posture, and the bar
  // would stay hidden until something happened to set it back.
  useEffect(() => release, [release]);
  const { width, height } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const detail = useFitDetail(id ?? '', signedIn);
  // The shelf under the pin: what came with the detail, then as
  // many pages after it as somebody keeps scrolling for.
  const seeded = useMemo(() => detail.data?.more ?? [], [detail.data?.more]);
  const more = useMoreUnder(id ?? '', signedIn, seeded);
  const shelf = useMemo(() => [...seeded, ...more.extra], [seeded, more.extra]);
  const react = useReact();
  const save = useSaveFit();
  const kinds = useReactionKinds(signedIn);
  const [boarding, setBoarding] = useState(false);
  const [sharing, setSharing] = useState<'screenshot' | 'tapped' | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [picking, setPicking] = useState(false);
  // Said in place rather than as an alert: this screen is mostly
  // photograph, and a dialog over it is a second thing to dismiss.
  const [problem, setProblem] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);
  // The caption and the tag row both open on one tap, and both
  // stay open: nobody asks for the whole thing and then wants it
  // folded away again.
  const [told, setTold] = useState(false);
  const [longCaption, setLongCaption] = useState(false);
  // The photograph's own shape. Seeded from whatever screen was showing
  // this fit a moment ago, so the frame opens at the right shape instead
  // of at a guess that snaps when the detail request lands.
  const [ratio, setRatio] = useState(() => shapeFor(id ?? '') ?? HERO.until);

  /**
   * The picture arrives by springing up, not by sliding in.
   *
   * **The transition people see is mostly this.** A pin opening is
   * the most-repeated move in the app, and the screen it pushes
   * cross-fades rather than sliding, so the photograph looks like it
   * grew out of the tile that was tapped rather than arriving from
   * off to the right.
   *
   * It is not a true shared element: Reanimated's shared transitions
   * sit behind an off-by-default experimental flag here, and the
   * app's most-repeated transition is the last place to spend an
   * experiment. What this buys instead is the part people actually
   * read as speed - the picture is already cached, already at its
   * own shape, and it overshoots very slightly on the way in, which
   * is what makes a transition feel crisp rather than merely quick.
   *
   * The constants live in `Pop`, with the arithmetic that says how
   * long they take. Damping under critical is what gives the
   * overshoot; the settling time is what stops it feeling slow.
   */
  const grow = useSharedValue(1);
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    if (reducedMotion) return;
    grow.value = PopFrom;
    grow.value = withSpring(1, Pop);
  }, [grow, reducedMotion]);
  const pop = useAnimatedStyle(() => ({ transform: [{ scale: grow.value }] }));

  const hide = useHideFit();
  const remove = useDeletePost();
  const setVisibility = useSetPostVisibility();

  /**
   * This fit, if it is one of ours.
   *
   * **From the detail response.** It was read out of the author's own
   * list, because the menu needs to know *which way the visibility
   * switch is set* and only that view carried it - but that list is
   * the thirty newest, so an author's thirty-first fit silently lost
   * "Make it private" and "Delete this fit" with nothing to explain
   * it. The response now carries both, so the menu is the same
   * whether a fit was reached from the board, a search result or the
   * profile, and however long ago it was posted.
   */
  const ours = detail.data?.mine
    ? { visibility: detail.data.visibility ?? 'public' }
    : null;

  const fit = detail.data?.fit ?? null;
  const author = detail.data?.author ?? null;
  const images = usePostImages(fit?.mediaAssetIds ?? []);
  const uri = images.data?.[fit?.mediaAssetIds[0] ?? ''] ?? null;

  // A screenshot is somebody trying to keep or send this. Offer the
  // real picture rather than letting them keep one with the status bar
  // in it and no credit on it.
  useScreenshotPrompt(() => {
    if (fit) setSharing('screenshot');
  });

  const tryItOn = () => {
    // Carries the fit over; does not pay for a picture on the way.
    //
    // This used to fire the render here and navigate afterwards, so
    // a tap meant a billed call of half a minute whether or not the
    // person stayed to look at it. The avatar screen leads with the
    // free figure now and asks before spending anything, which is the
    // same bargain the wardrobe assistant strikes - and the only
    // screen that should decide to spend is the one showing the
    // result.
    if (!fit) return;
    void tapFeedback();
    router.push({ pathname: '/avatar', params: { fit: fit.id } });
  };

  if (!signedIn) {
    return (
      <EmptyState
        status="blocked"
        title="Sign in to see this"
        body="Fits are posted by people with accounts, and seeing them needs one."
        action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
      />
    );
  }

  const shell = heroFrame(
    clampShape(ratio),
    width - Spacing.two * 2,
    // The picture's own height budget, which is what `tall` has always
    // meant. Taking the status bar out of it as well would narrow more
    // than a third of published covers instead of the three in a
    // hundred that are genuinely too tall for the screen.
    height * HERO.tall,
  );

  if (detail.isPending) {
    // The page in outline, at the size it will be. It used to be one
    // grey rectangle the width of the screen, and the whole page then
    // arrived at once over the top of it - so opening a pin lurched.
    //
    // The hero's shape is not guessed here: `ratio` carries what the
    // tile that was tapped already knew, so the frame is the size the
    // photograph will fill.
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <View
          accessible
          accessibilityRole="progressbar"
          accessibilityLabel="Loading this fit"
          accessibilityState={{ busy: true }}
          style={{ gap: Spacing.three }}>
          {/* The same frame the photograph will fill, by the same
              rule - a shell of a different size is a shell that moves
              when its content lands. */}
          <Skeleton
            width={shell.width}
            height={shell.height}
            radius={Radius.lg}
            style={{
              alignSelf: 'center',
              marginTop: insets.top + Spacing.three,
            }}
          />
          {/* The action row and the author line, in their places. */}
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
              paddingHorizontal: Spacing.three,
            }}>
            {/* The widths the real controls take, not numbers that
                looked about right: the heart and the bubble each
                carry a tally slot, the share glyph does not. Drawn
                any other way, the row moves as the fit arrives -
                which is the thing the reserved slot exists to
                prevent. */}
            <Skeleton
              width={ACTION_WIDTH}
              height={ActionIcon.size}
              radius={Radius.sm}
            />
            <Skeleton
              width={ACTION_WIDTH}
              height={ActionIcon.size}
              radius={Radius.sm}
            />
            <Skeleton
              width={ActionIcon.size}
              height={ActionIcon.size}
              radius={Radius.sm}
            />
          </View>
          <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
            <Skeleton width={160} height={14} />
            <Skeleton width={220} height={20} />
          </View>
          {/* And what comes under it, laid out as it will be. */}
          <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
            <Skeleton width={120} height={16} />
            <SkeletonMasonry count={4} />
          </View>
        </View>
      </View>
    );
  }

  if (!fit || !author) {
    return (
      <EmptyState
        status="empty"
        title="This fit is not here"
        body="It may have been taken down, or you may not be able to see it."
        action={{
          label: 'Back to Discover',
          onPress: () =>
            router.canGoBack() ? router.back() : router.replace('/'),
        }}
      />
    );
  }

  // The shape the server already knows, applied before the bytes
  // arrive. Without it the frame opened at a guess and resized to the
  // photograph as it decoded, so a picture somebody had just tapped
  // to look at stretched while they were looking at it.
  //
  // `ratio` is no longer only a fallback for the wait: it carries the
  // shape the previous screen already knew, so the two agree and the
  // frame does not move when the response arrives.
  // Through the same bounds the grid tiles use, so the card on the
  // board and the card on this page are the same shape.
  const shape = clampShape(detail.data?.fit.coverRatio ?? ratio);
  const frame = heroFrame(
    shape,
    width - Spacing.two * 2,
    // The picture's own height budget, which is what `tall` has always
    // meant. Taking the status bar out of it as well would narrow more
    // than a third of published covers instead of the three in a
    // hundred that are genuinely too tall for the screen.
    height * HERO.tall,
  );

  const myEmoji = kinds.data?.find((k) => k.kind === fit.myReaction)?.emoji;
  const shownTags = told ? fit.tags : fit.tags.slice(0, SHOWN_TAGS);

  // Shared by the caption and the invisible copy that measures it:
  // two different sizes would measure two different captions.
  const captionType = labelType(
    fit.captionIsDescribed ? FontSize.subhead : FontSize.title3,
    800,
  );
  // Hidden rather than inert when the link will not open: a Visit
  // button that does nothing is worse than no button.
  const site = safeSite(author.website);

  return (
    <>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ScrollView
        style={{ backgroundColor: colors.background }}
        refreshControl={refresh.control}
        contentContainerStyle={{
          // Clears the floating tab bar, which now sits over every
          // screen rather than only over the tabs.
          paddingBottom: BottomTabInset + insets.bottom + Spacing.six,
        }}
        showsVerticalScrollIndicator={false}
        // **Reports whether the picture or the browsing is what
        // somebody is doing.** At the top this page is one
        // photograph filling the screen and the tab bar sits on it;
        // past the picture it is a grid of other fits, where the bar
        // is how you leave. 16ms so the hand-off happens with the
        // finger rather than a frame behind it.
        scrollEventThrottle={16}
        onScroll={(event) => {
          onScroll(event);
          // **The shelf fetches its next slice before the bottom.**
          //
          // A ScrollView has no `onEndReached`, so the end is worked
          // out here. Two screens of warning rather than at the very
          // bottom: the next slice is a round trip plus a ranking
          // pass, and arriving at the end before it lands is exactly
          // what reads as the page running out.
          const { contentOffset, contentSize, layoutMeasurement } =
            event.nativeEvent;
          const fromBottom =
            contentSize.height - contentOffset.y - layoutMeasurement.height;
          if (
            fromBottom < layoutMeasurement.height * 2 &&
            more.hasNextPage &&
            !more.isFetchingNextPage
          ) {
            void more.fetchNextPage();
          }
        }}
        // A dragged picture and a scrolling page are the same
        // vertical gesture. Without this the page scrolls out from
        // under the finger that is panning the photograph.
        scrollEnabled={!zooming}>
        {/* The picture, whole, inside the screen.

            It was framed at 3:4 and covered, so every photograph that
            was not 3:4 lost something - usually the shoes or the head,
            because that is where a centre crop takes it from. The
            frame is the picture's own shape, so the picture reaches
            all four corners of it; a very tall one is held to
            `HERO.tall` of the screen by being drawn narrower, never by
            leaving a band of frame beside it. Inset and rounded, so
            the phone's own corners never clip it either. */}
        <Zoomable
          scale={zoom}
          width={frame.width}
          height={frame.height}
          onZoomedChange={setZooming}
          style={{ alignSelf: 'center' }}>
        <Animated.View
          onLayout={({ nativeEvent }) =>
            measureFocus(nativeEvent.layout.height)
          }
          style={[{
            width: frame.width,
            height: frame.height,
            // Centred, because a frame narrower than the screen that
            // sat against one edge would read as a mistake.
            alignSelf: 'center',
            // Below the status bar, not under it. The clock and the
            // signal bars are drawn over whatever is there, so a
            // photograph that starts at the top of the screen gets a
            // row of white glyphs across its best part - and on a
            // light picture they vanish into it, which is worse.
            marginTop: insets.top + Spacing.three,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            overflow: 'hidden',
            backgroundColor: colors.backgroundElement,
          }, pop]}>
          {uri ? (
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel={fit.caption ?? `A fit by ${fit.authorName}`}
              accessibilityHint="Opens the picture full size"
              animateEntrance={false}
              animatePress={false}
              onPress={() => {
                void tapFeedback();
                setZoomed(true);
              }}
              style={{ width: '100%', height: '100%' }}>
              <Image
                source={{ uri }}
                // **Always `cover`, never conditional.**
                //
                // It was `contain` whenever the frame fitted inside
                // the page's height budget, on the reasoning that
                // the frame was then the picture's own shape and the
                // two were identical. That reasoning missed the
                // clamp: `shape` is run through `clampShape`, so a
                // photograph taller than `SHAPE.tallest` gets a
                // frame that is deliberately *not* its own shape
                // while still fitting the page - and `contain` drew
                // it with a band of grey down each side, which is
                // precisely the letterboxing the one-shell rule
                // exists to remove.
                //
                // Where the frame really is the picture's shape this
                // is identical to `contain` and crops nothing. Where
                // it is not, filling the card is the whole point.
                // The uncropped picture is one tap away, full screen.
                contentFit="cover"
                // Decoded at its own resolution. The frame here takes
                // the picture's shape once it is known, so a decode
                // sized to the placeholder frame would be upscaled the
                // moment the real one arrives.
                allowDownscaling={false}
                cachePolicy="memory-disk"
                transition={ImageFade}
                onLoad={({ source }) =>
                  source?.width && source?.height
                    ? setRatio(source.width / source.height)
                    : undefined
                }
                style={{ width: '100%', height: '100%' }}
              />
            </MotionPressable>
          ) : (
            <View
              style={{ flex: 1, backgroundColor: colors.backgroundElement }}
            />
          )}

        </Animated.View>
        </Zoomable>

        {/* **Everything below the picture dissolves as it is pinched.**
            Once somebody is inside a photograph, the controls and
            the grid of other fits are not what they are looking at,
            and leaving them at full strength under a picture that
            has grown past its frame reads as two screens on top of
            each other. Driven from the same shared value the zoom
            is, so the fade is the same frame as the pinch rather
            than a round trip behind it. */}
        <Animated.View style={surround}>
        {/* The action row, directly under the picture it acts on. */}
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingTop: Spacing.three,
          }}>
          {/* One tap gives the default and takes it back; the five
              faces are a hold. Most people want the default and should
              not have to choose from a row of emoji to give it. */}
          <FitAction
            label={fit.myReaction ? 'Reacted' : 'React'}
            hint="Hold to pick a different reaction"
            emoji={myEmoji}
            icon={{ ios: 'heart', android: 'favorite_border', web: 'favorite' }}
            count={fit.reactions}
            onPress={() =>
              react.mutate({ id: fit.id, kind: fit.myReaction ? null : 'love' })
            }
            onLongPress={() => setPicking(true)}
          />

          {/* The bubble and its count, second. Three things you do to
              the picture sit together on the left; keeping it is a
              different kind of act and is held apart on the right. */}
          <Comments postId={fit.id} />

          <FitAction
            label="Share this fit"
            icon={{
              ios: 'square.and.arrow.up',
              android: 'ios_share',
              web: 'ios_share',
            }}
            onPress={() =>
              void shareFit({
                uri,
                authorName: fit.authorName,
                link: detail.data?.link,
              })
            }
          />

          <View style={{ flex: 1 }} />

          {/* Their own site, and only when they published one. A
              Visit button with nowhere to go is a control that does
              nothing, so it is absent rather than disabled. */}
          {site ? (
            <MotionPressable
              accessibilityRole="link"
              accessibilityLabel={`Visit ${author.name}'s site`}
              animateEntrance={false}
              scale={0.96}
              onPress={() => {
                void tapFeedback();
                openSite(site);
              }}
              style={{
                minHeight: TapTarget,
                justifyContent: 'center',
                paddingHorizontal: Spacing.four,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                backgroundColor: colors.backgroundElement,
              }}>
              <ThemedText style={labelType(FontSize.body, 800)}>
                Visit
              </ThemedText>
            </MotionPressable>
          ) : null}

          {/* Save, and then Saved.

              It said "Keep", which is this app's own word for the act
              and was the wrong place to spend a coinage: the control
              people look for on a picture is Save, and a familiar verb
              on the one button everybody presses is worth more than a
              distinctive one. The saved state is a dark pill rather
              than an outline, so which of the two it is reads from
              across the room. */}
          <MotionPressable
            accessibilityRole="button"
            accessibilityState={{ selected: fit.savedByMe }}
            accessibilityLabel={
              fit.savedByMe
                ? `Saved. ${fit.saves} in all. Tap to unsave.`
                : `Save this fit. ${fit.saves} people have.`
            }
            animateEntrance={false}
            scale={0.96}
            onPress={() => {
              void tapFeedback();
              const saving = !fit.savedByMe;
              save.mutate({ id: fit.id, saved: saving });
              // The note only makes sense for the direction that puts
              // it somewhere. Unsaving needs no receipt.
              if (saving) setJustSaved(true);
            }}
            style={{
              minHeight: TapTarget,
              justifyContent: 'center',
              paddingHorizontal: Spacing.four,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: fit.savedByMe ? colors.text : colors.accent,
            }}>
            <ThemedText
              style={{
                ...labelType(FontSize.body, 800),
                color: fit.savedByMe ? colors.background : colors.accentText,
              }}>
              {fit.savedByMe ? 'Saved' : 'Save'}
            </ThemedText>
          </MotionPressable>
        </View>

        {/* Said in place rather than as an alert: this screen is mostly
            photograph, and a dialog over it is a second thing to dismiss. */}
        {problem ? (
          <ThemedText
            type="small"
            selectable
            style={{ fontSize: FontSize.footnote, color: colors.danger }}>
            {problem}
          </ThemedText>
        ) : null}

        {/* Who posted it. */}
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={`${author.name}'s page`}
          animateEntrance={false}
          onPress={() => {
            // The header can be drawn from what this page already
            // knows, so the profile opens with a name on it rather
            // than a page of grey.
            seedMember(queries, { userId: author.userId, name: author.name });
            prefetchMember(queries, author.userId);
            void tapFeedback();
            router.push({
              pathname: '/member/[id]',
              params: { id: author.userId },
            });
          }}
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingTop: Spacing.four,
          }}>
          {/* A letter on a ground of its own, not a photograph: a
              face is the one thing a stranger's card could carry that
              identifies a real person by sight. */}
          <Monogram name={author.name} id={author.userId} size={40} />
          <View style={{ flex: 1, gap: Spacing.half }}>
            <ThemedText type="smallBold" numberOfLines={1}>
              {author.name}
            </ThemedText>
            {author.handle ? (
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.meta }}>
                @{author.handle}
              </ThemedText>
            ) : null}
          </View>
          {/* No Follow here.

              Following is a decision about a person, and the place to
              take it is their page, where there is enough of them to
              decide on. On a photograph it is a second call to action
              competing with the one this screen is for. */}
        </MotionPressable>

        {/* The author's words, or what is in the photograph.

            Set differently, because they are different things. A caption
            somebody wrote is theirs and reads at full weight; a line
            describing the clothes was read off the picture when they
            wrote none, and presenting that as a quote would put words in
            their mouth. */}
        {fit.caption ? (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.two,
              paddingHorizontal: Spacing.three,
              paddingTop: Spacing.three,
            }}>
            <View style={{ flex: 1 }}>
              <ThemedText
                themeColor={fit.captionIsDescribed ? 'textSecondary' : 'text'}
                // One line, with the rest behind the chevron beside
                // it. A caption is the author's and belongs here
                // whole; an essay of one standing between the
                // photograph and everything under it is the picture
                // competing with its own description.
                numberOfLines={told ? undefined : 1}
                style={captionType}>
                {fit.caption}
              </ThemedText>

              {/* The same caption again, unclamped and invisible,
                  purely to find out whether it fits.

                  **A clamped `Text` cannot report that it was
                  clamped.** `onTextLayout` describes the lines it
                  actually drew, so with `numberOfLines={1}` it
                  always answered "one line" - `lines.length > 1` was
                  never true, `longCaption` never became true, and
                  the control that opens a long caption never
                  appeared. The ellipsis was the only sign there was
                  more, with nothing to tap.

                  Measured rather than guessed from the character
                  count, because whether a caption fits depends on
                  the width it is given and the size it is set at. */}
              {!told ? (
                <ThemedText
                  aria-hidden
                  accessibilityElementsHidden
                  importantForAccessibility="no-hide-descendants"
                  pointerEvents="none"
                  onTextLayout={({ nativeEvent }) => {
                    if (nativeEvent.lines.length > 1) setLongCaption(true);
                  }}
                  style={[
                    captionType,
                    {
                      position: 'absolute',
                      left: 0,
                      right: 0,
                      opacity: 0,
                    },
                  ]}>
                  {fit.caption}
                </ThemedText>
              ) : null}
            </View>

            {/* One control for the caption and the tags both.

                A fit can carry a dozen hashtags, all useful to
                somebody and all of them a wall between the photograph
                and the board. Closed, this is a line and a row;
                open, it is everything the author wrote. */}
            {longCaption || fit.tags.length > SHOWN_TAGS ? (
              <MotionPressable
                accessibilityRole="button"
                accessibilityState={{ expanded: told }}
                accessibilityLabel={
                  told ? 'Show less' : 'Show the whole caption and every tag'
                }
                animateEntrance={false}
                scale={0.92}
                hitSlop={8}
                onPress={() => {
                  void tapFeedback();
                  setTold((was) => !was);
                }}
                style={{
                  width: 32,
                  height: 32,
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: Radius.full,
                  backgroundColor: colors.backgroundElement,
                }}>
                <SymbolView
                  name={
                    told
                      ? {
                          ios: 'chevron.up',
                          android: 'expand_less',
                          web: 'expand_less',
                        }
                      : {
                          ios: 'chevron.down',
                          android: 'expand_more',
                          web: 'expand_more',
                        }
                  }
                  size={14}
                  tintColor={colors.text}
                />
              </MotionPressable>
            ) : null}
          </View>
        ) : null}

        {fit.tags.length > 0 ? (
          <View
            style={{
              flexDirection: 'row',
              flexWrap: 'wrap',
              gap: Spacing.one,
              paddingHorizontal: Spacing.three,
              paddingTop: Spacing.two,
            }}>
            {/* A hashtag is a way through, not a label.

                Somebody reading "#linen" under a fit they like is
                asking the obvious next question, and a chip that does
                nothing when tapped is the app declining to answer it.
                The tap target is padded out to a usable height rather
                than left at the text's own. */}
            {shownTags.map((tag) => (
              <MotionPressable
                key={tag}
                accessibilityRole="link"
                accessibilityLabel={`Fits tagged ${tag}`}
                animateEntrance={false}
                scale={0.94}
                hitSlop={6}
                onPress={() => {
                  void tapFeedback();
                  router.push({ pathname: '/tag/[tag]', params: { tag } });
                }}
                style={{
                  minHeight: 32,
                  justifyContent: 'center',
                  paddingHorizontal: Spacing.two,
                  borderRadius: Radius.full,
                  backgroundColor: colors.backgroundElement,
                }}>
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{ fontSize: FontSize.meta }}>
                  #{tag}
                </ThemedText>
              </MotionPressable>
            ))}
          </View>
        ) : null}

        {shelf.length > 0 ? (
          <View style={{ paddingTop: Spacing.five, gap: Spacing.two }}>
            <ThemedText
              accessibilityRole="header"
              style={{
                ...labelType(20, 800),
                lineHeight: 24,
                paddingHorizontal: Spacing.three,
              }}>
              More to explore
            </ThemedText>
            {/* Two columns stacked independently, not wrapped rows.

                `flexWrap` made this a grid rather than a masonry: every
                wrapped row was as tall as its tallest tile, so a short
                one left a band of white beneath it and the gaps down
                the left column looked nothing like the gaps down the
                right. Two columns side by side, each with its own
                `gap`, puts the same distance between every pair of
                tiles - and `intoColumns` deals from the cover ratios
                the server already sent, so neither column runs long and
                the arrangement does not shuffle as pictures arrive. */}
            <View
              style={{
                flexDirection: 'row',
                gap: Spacing.two,
                paddingHorizontal: Spacing.three,
              }}>
              {intoColumns(shelf).map((lane, at) => (
                <View key={at} style={{ flex: 1, gap: Spacing.two }}>
                  {lane.map((other) => (
                    <FitCard
                      key={other.id}
                      fit={other}
                      onOpen={() =>
                        router.push({
                          pathname: '/fit/[id]',
                          params: { id: other.id },
                        })
                      }
                    />
                  ))}
                </View>
              ))}
            </View>

            {/* **The shelf does not end.**

                `more` used to be a fixed twelve computed once with
                the detail, so scrolling down here stopped - and
                opening one of those twelve opened a page that
                stopped too. It pages now, and so does the next one,
                so a reader can go pin to pin to pin without ever
                reaching a bottom.

                Related pins come first and the recommender tops it
                up once they run out: somebody who has scrolled this
                far is browsing, and more pins is a better answer
                than a wall. */}
            {more.isFetchingNextPage ? (
              <View style={{ paddingVertical: Spacing.four }}>
                <ActivityIndicator color={colors.accent} />
              </View>
            ) : null}
          </View>
        ) : null}
        </Animated.View>
        </ScrollView>

        {/* The way back and the menu, over the scroll rather than in it.

            They used to be absolutely positioned inside the picture's
            own frame, so scrolling down to the related pins carried
            them off the top of the screen and getting out meant
            scrolling all the way back up first. Out here they stay
            put. `box-none`, so only the chips themselves take a tap
            and the photograph underneath is still reachable. */}
        <View
          pointerEvents="box-none"
          style={{
            position: 'absolute',
            top: insets.top + Spacing.three + Spacing.two,
            left: Spacing.two,
            right: Spacing.two,
            flexDirection: 'row',
            justifyContent: 'space-between',
          }}>
          <Chip
            label="Back"
            icon={{
              ios: 'chevron.left',
              android: 'arrow_back',
              web: 'arrow_back',
            }}
            onPress={() => {
              // A shared link opens this screen with nothing behind
              // it, and `back` from there does nothing at all.
              // Discover is where a fit belongs, so that is where it
              // lands.
              if (router.canGoBack()) router.back();
              else router.replace('/');
            }}
          />
          <Chip
            label="More"
            icon={{
              ios: 'ellipsis',
              android: 'more_horiz',
              web: 'more_horiz',
            }}
            onPress={() => setMenuOpen(true)}
          />
        </View>
      </View>

      {/* Everything this fit can do. The corner used to carry a
          share button, which is one capability wearing the slot where
          all of them belong. */}
      <FitMenu
        fit={fit}
        uri={uri}
        link={detail.data?.link ?? ''}
        // What the look is made of, so the shop row can offer this
        // fit's pieces rather than a promise about them.
        items={detail.data?.items ?? []}
        // Enough on its own to shop the look: the catalogue is
        // searched per identified garment, with no tagging needed.
        cutPieces={detail.data?.cutPieces.length ?? 0}
        visible={menuOpen}
        onClose={() => setMenuOpen(false)}
        onHide={() => hide.mutate(fit.id)}
        onShare={() => setSharing('tapped')}
        // The author's own two actions, in the menu they are already
        // in. A tile on the profile carries no glyph of its own for
        // this: somebody deciding what to do about a photograph is
        // looking at the photograph.
        mine={
          ours
            ? {
                visibility: ours.visibility,
                onSetVisibility: (next) =>
                  setVisibility.mutate(
                    { postId: fit.id, visibility: next },
                    {
                      onError: () =>
                        setProblem('That could not be changed. Try again.'),
                    },
                  ),
                onDelete: () =>
                  remove.mutate(fit.id, {
                    onSuccess: () => {
                      // The fit this screen is about no longer exists,
                      // so staying on it would show a 404 somebody has
                      // to back out of.
                      if (router.canGoBack()) router.back();
                      else router.replace('/');
                    },
                    onError: () =>
                      setProblem('That could not be deleted. Try again.'),
                  }),
              }
            : undefined
        }
      />

      {/* The picture again, at the size of the screen, where it can
          be held to copy. */}
      <PhotoView
        uri={uri}
        fit={fit}
        more={detail.data?.more ?? []}
        visible={zoomed}
        onClose={() => setZoomed(false)}
        onOpenFit={(other) => {
          // Closed first, pushed after the dismissal has run. Doing
          // both in one frame put a modal dismissal and a screen push
          // on top of each other, and the picture appeared to snap
          // rather than to move.
          setZoomed(false);
          setTimeout(
            () => router.push({ pathname: '/fit/[id]', params: { id: other } }),
            Motion.fast,
          );
        }}
        onMore={() => {
          setZoomed(false);
          setMenuOpen(true);
        }}
        onShare={() =>
          void shareFit({
            uri,
            authorName: fit.authorName,
            link: detail.data?.link,
          })
        }
      />

      <ReactionPicker
        visible={picking}
        kinds={kinds.data ?? []}
        chosen={fit.myReaction}
        onClose={() => setPicking(false)}
        onPick={(kind) => {
          setPicking(false);
          react.mutate({
            id: fit.id,
            kind: kind === fit.myReaction ? null : kind,
          });
        }}
      />

      <ShareSheet
        fit={fit}
        visible={sharing !== null}
        reason={sharing ?? undefined}
        link={detail.data?.link ?? ''}
        onClose={() => setSharing(null)}
        onSave={() => save.mutate({ id: fit.id, saved: true })}
        onBoard={() => setBoarding(true)}
        onTryOn={() => void tryItOn()}
      />

      {/* Where it went, and the way to sort it. The save already
          happened; this is not a dialog asking which board. */}
      <SavedNote
        visible={justSaved && fit.savedByMe}
        where="your profile"
        uri={uri}
        onOrganise={() => setBoarding(true)}
        onDone={() => setJustSaved(false)}
      />

      {/* Boards hold published fits as themselves, so this pins the fit
          rather than whatever look it happened to be tagged with. */}
      <PinToBoard
        postId={fit.id}
        title={fit.caption ?? `${fit.authorName}'s fit`}
        visible={boarding}
        onClose={() => setBoarding(false)}
      />
    </>
  );
}

/** One floating control over the photograph. */
function Chip({
  label,
  icon,
  onPress,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.92}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        width: TapTarget,
        height: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.full,
        backgroundColor: colors.background,
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.18)',
      }}>
      <SymbolView name={icon} size={18} tintColor={colors.text} />
    </MotionPressable>
  );
}

