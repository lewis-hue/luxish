import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { AnimatePresence, MotiView } from 'moti';
import { useMemo, useState } from 'react';
import * as Linking from 'expo-linking';
import { SymbolView } from 'expo-symbols';
import { Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  EMPTY_APPEARANCE,
  isWorking,
  useAvatar,
  useCreateAvatar,
  useTryOnFit,
  useRenders,
  useSetAppearance,
  type Appearance,
  type Piece,
  type Render,
} from '@/api/queries/avatar';
import { useFitDetail } from '@/api/queries/discover-feed';
import { usePostImages } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { wearCutPieces } from '@/features/stylist/try-on';
import { EmptyState } from '@/components/ui/empty-state';
import {
  MotionPressable,
  successFeedback,
  tapFeedback,
  useMotiTiming,
} from '@/components/ui/motion';
import {
  AspectRatio,
  Colors,
  FontSize,
  Motion,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { webSearchUrlForDescription } from '@/features/discover/visual-search';
import { keepToPhotos } from '@/features/avatar/keep';
import { useFavouriteGarments } from '@/features/discover/saved';
import { useWardrobe, type WardrobeEntry } from '@/features/wardrobe/store';
import {
  OutfitFigure,
  type Presentation,
} from '@/features/avatar/figure';
import { useScheme } from '@/hooks/use-theme';

/**
 * Whatever was thrown, as something a person can read.
 *
 * The typed client raises an `ApiError` carrying the server's own message,
 * which is already written for a reader. Anything else gets a plain sentence
 * rather than a stack trace.
 */
function describe(caught: unknown): string {
  const message = caught instanceof Error ? caught.message.trim() : '';
  return message || 'Something went wrong. Try that again in a moment.';
}

/**
 * The vocabularies, in the order they are offered.
 *
 * They mirror `app.workers.avatar` exactly — the server rejects anything it
 * does not recognise — and each one ends with a way to say nothing, because
 * every field here is optional by design.
 */
const PRESENTATION = [
  ['feminine', 'Feminine'],
  ['masculine', 'Masculine'],
  ['androgynous', 'Androgynous'],
  ['unspecified', 'Rather not say'],
] as const;

const BUILD = [
  ['slim', 'Slim'],
  ['average', 'Average'],
  ['athletic', 'Athletic'],
  ['curvy', 'Curvy'],
  ['plus', 'Plus'],
  ['unspecified', 'Rather not say'],
] as const;

const HEIGHT = [
  ['tall', 'Tall'],
  ['average', 'Average'],
  ['short', 'Short'],
  ['unspecified', 'Rather not say'],
] as const;

const AGE = [
  ['20s', '20s'],
  ['30s', '30s'],
  ['40s', '40s'],
  ['50s', '50s'],
  ['60s_plus', '60s +'],
  ['unspecified', 'Rather not say'],
] as const;

const SKIN_TONE = [
  ['very_fair', 'Very fair'],
  ['fair', 'Fair'],
  ['medium', 'Medium'],
  ['olive', 'Olive'],
  ['brown', 'Brown'],
  ['dark_brown', 'Dark brown'],
  ['deep', 'Deep'],
  ['unspecified', 'Rather not say'],
] as const;

/**
 * Your avatar, and outfits on it.
 *
 * The screen exists to answer one question that a grid of clothes cannot:
 * what would this look like on me. So the figure is the screen. Everything
 * else is arranged around it and kept quiet.
 *
 * **The appearance is asked, never worked out.** Nothing here reads
 * presentation off somebody's wardrobe, and every field can be left unsaid.
 * An avatar drawn from nothing is still an avatar; it just has fewer details
 * pinned.
 *
 * **Both model calls are explicit.** Drawing the avatar and dressing it are
 * billed, so neither happens on arrival, on scroll, or as a side effect of
 * answering a question. They happen because somebody tapped.
 */
export default function AvatarScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const avatar = useAvatar(signedIn);
  const renders = useRenders(signedIn);
  const setAppearance = useSetAppearance();
  const create = useCreateAvatar();
  /** A fit carried in from Discover's "Try it on". */
  const { fit: fitParam } = useLocalSearchParams<{ fit?: string }>();

  /**
   * The carried fit's own garments, ready for the figure to wear.
   *
   * **Free, and the real clothes.** The render below describes the
   * outfit to an image model and pays it to draw somebody wearing
   * that description, which produces something *like* the fit. The
   * server cuts each garment out of the photograph instead, so
   * these are the things themselves.
   *
   * Empty for a fit nobody has read yet, or one nothing could be
   * cut from, and the screen then offers only the render - which is
   * what it offered for everything before this.
   */
  const carried = useFitDetail(fitParam ?? '', signedIn && Boolean(fitParam));
  // Memoised because the `?? []` makes a new array every render,
  // which would re-dress the figure on each one.
  const cut = useMemo(
    () => carried.data?.cutPieces ?? [],
    [carried.data?.cutPieces],
  );
  const cutImages = usePostImages(cut.map((piece) => piece.mediaAssetId));
  const wearingCut = useMemo(
    () => wearCutPieces(cut, cutImages.data ?? {}),
    [cut, cutImages.data],
  );
  const wearing = useTryOnFit();

  // The newest finished picture, and whether anything is still being drawn.
  // Both come from the render list rather than from mutation state: the work
  // happens on a worker, so a screen reopened mid-draw has to find that out
  // from the server rather than from a hook that has forgotten.
  const newest = (renders.data ?? []).find((render) => render.state === 'ready');
  const drawing = (renders.data ?? []).find((render) => isWorking(render.state));
  const lastFailure = (renders.data ?? []).find(
    (render) => render.state === 'failed',
  );

  // Unsaved answers only, laid over whatever the server holds. Copying the
  // server value into state would need an effect to seed it, and that effect
  // would overwrite an answer somebody had just tapped the moment a refetch
  // landed. An overlay has no such window: the stored value shows through
  // every field that has not been touched.
  const [edits, setEdits] = useState<Partial<Appearance>>({});
  const [worn, setWorn] = useState<{ uri: string; label: string } | null>(null);
  // Both actions here are billed calls to an external service, so both can
  // fail for reasons nothing to do with the person tapping. An unhandled
  // rejection surfaces as a red box over the whole app; this turns it into a
  // line on the screen that says what happened.
  const [problem, setProblem] = useState<string | null>(null);
  const [keeping, setKeeping] = useState(false);
  const [kept, setKept] = useState(false);
  // Open by default only when there is nothing drawn yet: on a fresh account
  // the questions *are* the screen, and on a returning one the picture is.
  const [editingLooks, setEditingLooks] = useState(false);

  const draft: Appearance = {
    ...(avatar.data?.appearance ?? EMPTY_APPEARANCE),
    ...edits,
  };
  const commit = (patch: Partial<Appearance>) =>
    setEdits((prior) => ({ ...prior, ...patch }));

  const showing = worn?.uri ?? newest?.uri ?? avatar.data?.uri ?? null;
  // Busy means "a picture is being drawn", which outlives the request that
  // asked for it. The mutation settles in half a second; the worker takes
  // fifteen to twenty-seven.
  const busy = Boolean(drawing) || create.isPending;
  // What is in the picture on screen, labelled, as it was asked for.
  const shown: Render | undefined = worn ? undefined : newest;

  // What of their own would work with this. Matched by slot and category
  // against the pieces in the picture — the same vocabulary both sides
  // already use, so no model call and nothing to calibrate.
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);
  const matches = useMemo(
    () => matchingGarments(wardrobe.entries, shown?.pieces ?? []),
    [wardrobe.entries, shown],
  );

  const keep = async () => {
    if (!showing || keeping) return;
    void tapFeedback();
    setProblem(null);
    setKeeping(true);
    try {
      await keepToPhotos(showing);
      setKept(true);
      void successFeedback();
    } catch (caught) {
      setProblem(describe(caught));
    } finally {
      setKeeping(false);
    }
  };

  if (!signedIn) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center' }}>
        <EmptyState
          status="blocked"
          title="Sign in to build your avatar"
          body="Your avatar is drawn on the server and kept with your account."
          action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
        />
      </View>
    );
  }

  return (
    <ScrollView
      refreshControl={refresh.control}
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{
        paddingHorizontal: Spacing.three,
        paddingBottom: insets.bottom + Spacing.six,
        gap: Spacing.four,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ gap: Spacing.one, marginTop: Spacing.two }}>
        <ThemedText style={{ ...labelType(34, 800), lineHeight: 38 }}>
          {showing ? 'This is you' : 'Build your avatar'}
        </ThemedText>

      </View>

      {/* The free figure leads; the drawn one replaces it.

          **Same bargain as the wardrobe assistant.** A render is a
          billed call of fifteen to twenty-seven seconds, so the
          screen opens with the stylized figure - which costs nothing
          and is already on the device - and a photoreal one is asked
          for rather than assumed. The figure that shows is the one
          chosen by the presentation set below, so the settings on
          this screen are the settings the assistant uses too.

          Once there is a drawn picture it takes over: somebody who
          has paid for one should not have to ask twice to see it. */}
      {showing ? (
        <Figure uri={showing} label={worn?.label ?? null} busy={busy} />
      ) : (
        <OutfitFigure
          // **Wearing the fit's own garments, cut from its
          // photograph.** Free and immediate: the clothes are the
          // real ones, so nothing is redrawn and nothing drifts.
          // The paid render below is for somebody who wants it
          // photoreal, which is a different question.
          pieces={wearingCut}
          presentation={
            (avatar.data?.appearance.presentation ??
              'unspecified') as Presentation
          }
          label={
            wearingCut.length > 0
              ? 'This fit on your figure.'
              : 'Your figure. Set how you look below.'
          }
        />
      )}

      {/* A fit carried in from Discover, waiting to be asked for. */}
      {fitParam && !busy ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={
            wearingCut.length > 0 ? 'See it photoreal' : 'See this fit on you'
          }
          accessibilityHint="Draws it on your avatar. Takes about half a minute."
          accessibilityState={{ busy: wearing.isPending }}
          animateEntrance={false}
          disabled={wearing.isPending}
          onPress={() => {
            void tapFeedback();
            setProblem(null);
            wearing.mutate(fitParam, {
              onError: () =>
                setProblem('That could not be started. Try again in a moment.'),
            });
          }}
          style={{
            minHeight: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.full,
            backgroundColor: colors.accent,
            opacity: wearing.isPending ? 0.5 : 1,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.accentText }}>
            {wearing.isPending
              ? 'Drawing it on you'
              : wearingCut.length > 0
                ? 'See it photoreal'
                : 'See this fit on you'}
          </ThemedText>
        </MotionPressable>
      ) : null}

      {problem ? (
        <ThemedText
          selectable
          style={{ ...labelType(FontSize.subhead, 400), color: colors.danger }}>
          {problem}
        </ThemedText>
      ) : null}

      {/* Keep it.

          Without this the only way a picture leaves the app is a
          screenshot, which carries the status bar and the tab chrome and
          none of the resolution. Shown only when there is something
          finished to save: a button over a placeholder is a button that
          fails. */}
      {showing && !busy ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Save this picture to your photos"
          accessibilityState={{ busy: keeping, disabled: keeping }}
          disabled={keeping}
          animateEntrance={false}
          scale={0.98}
          onPress={() => void keep()}
          style={{
            minHeight: TapTarget,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'center',
            gap: Spacing.two,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.border,
            opacity: keeping ? 0.6 : 1,
          }}>
          <SymbolView
            name={{
              ios: 'square.and.arrow.down',
              android: 'download',
              web: 'download',
            }}
            size={18}
            tintColor={colors.text}
          />
          <ThemedText type="smallBold">
            {keeping ? 'Saving' : kept ? 'Saved to your photos' : 'Save this picture'}
          </ThemedText>
        </MotionPressable>
      ) : null}

      {/* A failure the worker recorded, which outlives the request that
          asked for it: a screen reopened after a failed draw has to find
          that out from the server. */}
      {!problem && lastFailure?.error ? (
        <View
          style={{
            padding: Spacing.three,
            gap: Spacing.half,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.danger,
          }}>
          <ThemedText type="label" style={{ color: colors.danger }}>
            Last one did not work
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {lastFailure.error}
          </ThemedText>
        </View>
      ) : null}

      {problem ? (
        <View
          style={{
            padding: Spacing.three,
            gap: Spacing.half,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.danger,
          }}>
          {/* Carried on text and a label rather than on colour alone, which
              is what WCAG 1.4.1 asks for and what ADR-019 already settled
              for every other state in this app. */}
          <ThemedText type="label" style={{ color: colors.danger }}>
            Did not work
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {problem}
          </ThemedText>
        </View>
      ) : null}

      {/*
        What is in the picture.
        
        Labelled from what was asked for, never read back out of the finished
        image: when the avatar is dressed in a look the garments are already
        known exactly, so a vision call would be paying to guess at something
        in hand. Each one searches the web, which is how somebody buys it.
      */}
      {shown && shown.pieces.length > 0 ? (
        <View style={{ gap: Spacing.two }}>
          <ThemedText type="label" themeColor="textSecondary">
            What you are wearing
          </ThemedText>
          {shown.pieces.map((piece) => (
            <PieceRow key={`${piece.name}-${piece.colour ?? ''}`} piece={piece} />
          ))}
        </View>
      ) : null}

      {/*
        Yours that would work with it.

        Matched on the categories both sides already speak — no model call,
        nothing to calibrate, and a person can check every row against their
        own wardrobe. Shown only when there is something to show: "nothing in
        your wardrobe matches" is a sentence nobody needs under a picture
        they just made.
      */}
      {matches.length > 0 ? (
        <View style={{ gap: Spacing.two }}>
          <ThemedText type="label" themeColor="textSecondary">
            From your wardrobe
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {matches.length === 1
              ? 'One piece you own would work with this.'
              : `${matches.length} pieces you own would work with this.`}
          </ThemedText>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.one }}>
            {matches.map((entry) => (
              <View
                key={entry.id}
                style={{
                  paddingHorizontal: Spacing.three,
                  paddingVertical: Spacing.one,
                  borderRadius: Radius.full,
                  borderWidth: 1,
                  borderColor: colors.border,
                }}>
                <ThemedText type="small" style={{ fontSize: FontSize.footnote }}>
                  {entry.name}
                </ThemedText>
              </View>
            ))}
          </View>
        </View>
      ) : null}

      {/*
        The questions, folded away.

        Five rows of chips sat permanently between the picture and the button
        that redraws it, on a screen whose point is the picture. They are
        setup: answered once, changed rarely, and worth one tap rather than a
        permanent third of the scroll. The row shows the current answer, so
        folding them hides the controls and not what was said.
      */}
      <View style={{ gap: Spacing.three }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="How you look"
          accessibilityState={{ expanded: editingLooks }}
          animateEntrance={false}
          scale={0.99}
          onPress={() => {
            void tapFeedback();
            setEditingLooks((was) => !was);
          }}
          style={{
            minHeight: TapTarget,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: Spacing.two,
          }}>
          <View style={{ flex: 1, gap: Spacing.half }}>
            <ThemedText type="label" themeColor="textSecondary">
              How you look
            </ThemedText>
            <ThemedText type="small" numberOfLines={1}>
              {summarise(draft)}
            </ThemedText>
          </View>
          <SymbolView
            name={{
              ios: editingLooks ? 'chevron.up' : 'chevron.down',
              android: editingLooks ? 'expand_less' : 'expand_more',
              web: 'expand_more',
            }}
            size={18}
            tintColor={colors.textSecondary}
          />
        </MotionPressable>


        {editingLooks ? (
          <>
        <Choice
          label="Presentation"
          field="presentation"
          value={draft.presentation}
          options={PRESENTATION}
          commit={commit}
        />
        <Choice
          label="Build"
          field="bodyType"
          value={draft.bodyType}
          options={BUILD}
          commit={commit}
        />
        <Choice
          label="Height"
          field="height"
          value={draft.height}
          options={HEIGHT}
          commit={commit}
        />
        <Choice
          label="Age"
          field="ageBand"
          value={draft.ageBand}
          options={AGE}
          commit={commit}
        />
        <Choice
          label="Skin tone"
          field="skinTone"
          value={draft.skinTone}
          options={SKIN_TONE}
          commit={commit}
        />

            <View style={{ gap: Spacing.two }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={avatar.data?.assetId ? 'Draw it again' : 'Draw my avatar'}
          accessibilityState={{ busy: create.isPending, disabled: busy }}
          disabled={busy}
          animateEntrance={false}
          onPress={async () => {
            void tapFeedback();
            setProblem(null);
            try {
              // Saved first: the drawing reads the stored appearance, so
              // sending them together would draw the previous answer.
              await setAppearance.mutateAsync(draft);
              setWorn(null);
              await create.mutateAsync();
              void successFeedback();
            } catch (caught) {
              setProblem(describe(caught));
            }
          }}
          style={{
            minHeight: TapTarget + 8,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.borderStrong,
            opacity: busy ? 0.45 : 1,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.text }}>
            {create.isPending
              ? 'Drawing'
              : avatar.data?.assetId
                ? 'Draw it again'
                : 'Draw my avatar'}
          </ThemedText>
        </MotionPressable>

            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta, textAlign: 'center' }}>
              A drawing, not a photograph. Private to your account.
            </ThemedText>
            </View>
          </>
        ) : null}
      </View>
    </ScrollView>
  );
}

/**
 * The figure, and the one piece of motion on the screen.
 *
 * A cross-fade between the old picture and the new one, because that is what
 * the feature *is*: the same person, the clothes changing. A slide or a
 * bounce would animate the arrival of an image; this animates the change of
 * an outfit, which is the thing somebody is actually watching for.
 *
 * `AnimatePresence` keeps the outgoing picture mounted long enough to fade
 * under the incoming one, so there is no blank frame between two outfits.
 */
function Figure({
  uri,
  label,
  busy,
}: {
  uri: string | null;
  label: string | null;
  busy: boolean;
}) {
  const colors = Colors[useScheme()];
  const timing = useMotiTiming();

  // Measured off the picture rather than assumed. The generator does not
  // return a consistent shape — 1120 x 2240 for the avatar prompt, 1280 x
  // 1920 for the Discover covers — so a fixed box either squashes the figure
  // or strands it in empty space. The token is the height to start at; this
  // is the height to keep.
  const [ratio, setRatio] = useState(AspectRatio.avatar);

  return (
    <View
      style={{
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
        aspectRatio: ratio,
      }}>
      <AnimatePresence>
        {uri ? (
          <MotiView
            key={uri}
            from={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={timing({ duration: Motion.slow })}
            style={{ position: 'absolute', inset: 0 }}>
            <Image
              source={{ uri }}
              contentFit="contain"
              cachePolicy="memory-disk"
              onLoad={({ source }) => {
                if (source.width > 0 && source.height > 0) {
                  setRatio(source.width / source.height);
                }
              }}
              accessible
              accessibilityLabel={
                label ? `Your avatar wearing ${label}` : 'Your avatar'
              }
              style={{ width: '100%', height: '100%' }}
            />
          </MotiView>
        ) : null}
      </AnimatePresence>

      {!uri && !busy ? (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
          <ThemedText type="small" themeColor="textSecondary">
            Nothing drawn yet
          </ThemedText>
        </View>
      ) : null}

      {/* While a billed call is running. A slow pulse on the whole surface
          rather than a spinner: the thing being waited for is a picture, and
          a spinner in the middle of one reads as a failure to load it. */}
      {busy ? (
        <MotiView
          from={{ opacity: 0.08 }}
          animate={{ opacity: 0.22 }}
          transition={timing({ duration: 900, loop: true, repeatReverse: true })}
          accessible
          accessibilityLabel="Drawing"
          accessibilityState={{ busy: true }}
          style={{ position: 'absolute', inset: 0, backgroundColor: colors.text }}
        />
      ) : null}

      {label && !busy ? (
        <MotiView
          from={{ opacity: 0, translateY: 6 }}
          animate={{ opacity: 1, translateY: 0 }}
          transition={timing({ duration: Motion.base, delay: Motion.slow })}
          style={{
            position: 'absolute',
            left: Spacing.two,
            bottom: Spacing.two,
            paddingHorizontal: Spacing.two,
            paddingVertical: Spacing.one,
            borderRadius: Radius.full,
            backgroundColor: 'rgba(16,12,11,0.72)',
          }}>
          <ThemedText
            type="small"
            style={{ fontSize: FontSize.meta, color: 'rgba(255,255,255,0.94)' }}>
            {label}
          </ThemedText>
        </MotiView>
      ) : null}
    </View>
  );
}

/**
 * What somebody said about themselves, in one line.
 *
 * Shown on the folded row so collapsing the questions hides the controls
 * rather than the answers. "Not said yet" rather than an empty string,
 * because a blank line under a heading reads as a bug rather than as a
 * question nobody has answered.
 */
function summarise(appearance: Appearance): string {
  const said = [
    LABEL_OF.height[appearance.height],
    LABEL_OF.bodyType[appearance.bodyType],
    LABEL_OF.presentation[appearance.presentation],
    LABEL_OF.ageBand[appearance.ageBand],
    LABEL_OF.skinTone[appearance.skinTone],
  ].filter(Boolean);
  return said.length ? said.join(', ') : 'Not said yet';
}

/** Chip labels, keyed so one line can be built from the stored values. */
const LABEL_OF = {
  presentation: Object.fromEntries(PRESENTATION) as Record<string, string>,
  bodyType: Object.fromEntries(BUILD) as Record<string, string>,
  height: Object.fromEntries(HEIGHT) as Record<string, string>,
  ageBand: Object.fromEntries(AGE) as Record<string, string>,
  skinTone: Object.fromEntries(SKIN_TONE) as Record<string, string>,
};

/**
 * Which of somebody's own clothes would work with the picture.
 *
 * Matched on the garment category both sides already speak, which is why
 * this needs no model call and nothing calibrating: the pieces carry the
 * category they were requested with, and a wardrobe entry carries the one it
 * was sorted into. A person can check every row against their own cupboard.
 *
 * **Deliberately not a similarity score.** A number next to somebody's own
 * jumper, derived from a model and uncalibrated, is a confident claim about
 * their clothes that they are the only person able to disprove — and this
 * codebase already measured what uncalibrated confidence looks like on the
 * style classifier. A match is shown or it is not.
 *
 * Samples are excluded: suggesting the demo wardrobe would be recommending
 * clothes nobody owns.
 */
function matchingGarments(
  entries: readonly WardrobeEntry[],
  pieces: readonly Piece[],
): readonly WardrobeEntry[] {
  if (pieces.length === 0) return [];
  const wanted = new Set(
    pieces
      .map((piece) => piece.category?.toLowerCase())
      .filter((category): category is string => Boolean(category)),
  );
  if (wanted.size === 0) return [];

  return entries
    .filter(
      (entry) =>
        !entry.isSample &&
        entry.availability === 'available' &&
        entry.categoryId !== null &&
        wanted.has(entry.categoryId.toLowerCase()),
    )
    // Favourites first: of two jumpers that both fit, the one somebody said
    // they love is the better suggestion.
    .sort((a, b) => Number(b.isFavourite) - Number(a.isFavourite))
    .slice(0, 8);
}

/**
 * One garment in the picture: what it is, and where to buy it.
 *
 * The label is what was *asked for*, so it is exact rather than a model's
 * reading of its own output. Tapping opens a shopping search, which is the
 * honest version of "buy this": this app has no retail integration, and
 * pretending to one would be a fixture reading as a live checkout.
 */
function PieceRow({ piece }: { piece: Piece }) {
  const colors = Colors[useScheme()];
  const search = () => {
    void tapFeedback();
    void Linking.openURL(
      webSearchUrlForDescription({
        name: piece.name,
        colour: piece.colour,
        category: piece.category,
      }),
    );
  };

  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={`Find ${piece.colour ? `${piece.colour} ` : ''}${piece.name} to buy`}
      onPress={search}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: Spacing.three,
        minHeight: TapTarget,
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
        opacity: pressed ? 0.7 : 1,
      })}>
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText type="small" numberOfLines={1}>
          {piece.colour ? `${piece.colour} ${piece.name.toLowerCase()}` : piece.name}
        </ThemedText>
        {piece.category ? (
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            {piece.category}
          </ThemedText>
        ) : null}
      </View>
      <ThemedText type="small" style={{ fontSize: FontSize.footnote, color: colors.accent }}>
        Find
      </ThemedText>
    </Pressable>
  );
}

/** One row of mutually exclusive answers, none of them required. */
function Choice<K extends keyof Appearance>({
  label,
  field,
  value,
  options,
  commit,
}: {
  label: string;
  field: K;
  value: Appearance[K];
  options: readonly (readonly [Appearance[K], string])[];
  commit: (patch: Partial<Appearance>) => void;
}) {
  const colors = Colors[useScheme()];

  return (
    <View style={{ gap: Spacing.one }}>
      <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.footnote }}>
        {label}
      </ThemedText>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.one }}>
        {options.map(([id, text]) => {
          const active = id === value;
          return (
            <Pressable
              key={id}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              hitSlop={6}
              onPress={() => {
                void tapFeedback();
                commit({ [field]: id } as Partial<Appearance>);
              }}
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
                style={{
                  fontSize: FontSize.footnote,
                  color: active ? colors.background : colors.textSecondary,
                }}>
                {text}
              </ThemedText>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
