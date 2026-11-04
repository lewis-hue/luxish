import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { MotiView } from 'moti';
import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  Modal,
  Pressable,
  View,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import {
  MotionPressable,
  tapFeedback,
  useMotiTiming,
} from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { BRAND } from '@/branding';
import { PictureActions } from '@/features/avatar/picture-actions';
import { usePostImages } from '@/api/queries/post-media';
import { OutfitFigure } from '@/features/avatar/figure';
import { type Turn } from '@/features/stylist/conversation';
import { wearGaps, wearOwned } from '@/features/stylist/try-on';
import type { WardrobeEntry } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/**
 * The conversation, drawn.
 *
 * **Only one side of a conversation gets a bubble.** The person's own
 * words sit in a tinted capsule on the right; the stylist's answer is
 * set as plain text straight onto the page. That is not a style
 * preference, it is what fixes the screen somebody complained about:
 * two columns of bubbles leave the reply about forty per cent of the
 * width, and an answer that runs to four sentences then arrives as a
 * narrow grey brick pushed against the left edge. Text on the page has
 * the whole measure, which is the only width a paragraph reads well at.
 *
 * It also removes a real bug. The reply was a `maxWidth: '88%'` box
 * holding a row of `[icon][flex: 1 text]`, and when that percentage
 * failed to resolve against its parent the row sized itself to the
 * unwrapped sentence and the text was clipped mid-word rather than
 * wrapped - "and super ba" with the rest of the line simply gone.
 * Nothing here depends on a percentage any more: the stylist's block
 * stretches, so its width is definite and the text must wrap.
 *
 * **Everything the stylist produces is a turn, including a picture.**
 * A figure wearing an outfit is the answer to "show me that on me", so
 * it sits in the thread beside the sentence that led to it rather than
 * in a panel of its own - which is what lets somebody look at it and
 * then keep talking.
 *
 * The composer is not here. It belongs below this, pinned, so the
 * newest reply is the thing nearest the thumb and the box does not
 * push the conversation off the screen as it grows.
 */

/**
 * The figure the wait is drawn on.
 *
 * A neutral stand-in, and deliberately a photograph of a mannequin
 * rather than a grey rectangle. The box that used to be here reserved
 * the right shape and filled it with nothing, so half a minute of
 * drawing looked like half a minute of an empty card - which is what
 * "it is not using a mannequin to show the outfit" was describing.
 *
 * What finally lands may be their own avatar instead; the server
 * prefers it when they have made one (`domain/mannequin.figure_to_dress`).
 * This is only what stands there in the meantime, so one neutral figure
 * is the honest choice rather than guessing at theirs.
 */
const STAND_IN = require('../../../assets/images/mannequins/androgynous-average.webp');

/** Just enough of a render for the thread to draw it. */
export interface RenderLike {
  id: string;
  state: string;
  uri: string | null;
  error: string | null;
}

export function Thread({
  turns,
  onTryOn,
  renders = [],
  wardrobe = [],
  onEdit,
  onForget,
}: {
  turns: readonly Turn[];
  /** Ask for this turn's outfit on the figure. */
  onTryOn: (turn: Turn) => void;
  /** Every figure in flight or finished, polled elsewhere. */
  renders?: readonly RenderLike[];
  /**
   * Their clothes, so a look can be drawn here for nothing.
   *
   * See `wearOwned`: the verdict names garment ids this person
   * owns and every one has a cut-out already on the device, so
   * the figure is a composite rather than a generation.
   */
  wardrobe?: readonly WardrobeEntry[];
  /** Take a question back into the composer to ask it differently. */
  onEdit?: (turn: Turn) => void;
  /** Remove a question and the answer it produced. */
  onForget?: (turn: Turn) => void;
}) {
  if (turns.length === 0) return null;
  return (
    // `stretch`, so every child has a definite width to lay out against.
    // This is what the reply's wrapping depends on.
    <View style={{ alignSelf: 'stretch', gap: Spacing.four }}>
      {turns.map((turn) => (
        <Bubble
          key={turn.id}
          turn={turn}
          onTryOn={onTryOn}
          // Only under the most recent "you own nothing for this".
          // Repeating it under every past one would be three
          // identical buttons answering the same question.
          render={
            turn.renderId
              ? renders.find((r) => r.id === turn.renderId)
              : undefined
          }
          wardrobe={wardrobe}
          onEdit={onEdit}
          onForget={onForget}
        />
      ))}
    </View>
  );
}

function Bubble({
  turn,
  onTryOn,
  render,
  wardrobe = [],
  onEdit,
  onForget,
}: {
  turn: Turn;
  onTryOn: (turn: Turn) => void;
  render?: RenderLike;
  wardrobe?: readonly WardrobeEntry[];
  onEdit?: (turn: Turn) => void;
  onForget?: (turn: Turn) => void;
}) {
  const colors = Colors[useScheme()];
  const mine = turn.who === 'you';
  const [showActions, setShowActions] = useState(false);
  const [worn, setWorn] = useState(false);
  // Built from the verdict's own ids against their wardrobe. Empty
  // when the answer named nothing of theirs, which is exactly when
  // there is nothing to draw.
  const owned = useMemo(
    () => wearOwned(turn.verdict?.using ?? [], wardrobe),
    [turn.verdict?.using, wardrobe],
  );

  // **And the pieces they do not own, so the look is still shown.**
  //
  // The reported failure: asked how baggy skater shorts, a white
  // tee and white sneakers would look, the reply named all three,
  // linked all three, and showed nothing - while every answer
  // around it carried a figure wearing the look. An answer that can
  // only say no is not one somebody can act on.
  //
  // These are drawn server-side once per phrase and shared by every
  // account, so the second person to ask about white sneakers waits
  // for a row lookup. A piece still being drawn simply has no
  // picture yet and is left off the figure until it does.
  const gapAssets = useMemo(
    () =>
      (turn.pieces ?? [])
        .map((piece) => piece.asset_id)
        .filter((id): id is string => Boolean(id)),
    [turn.pieces],
  );
  const gapImages = usePostImages(gapAssets);
  const wearing = useMemo(
    () => [...owned, ...wearGaps(turn.pieces ?? [], gapImages.data ?? {})],
    [owned, turn.pieces, gapImages.data],
  );

  // Each missing piece with the shops that sell it. Grouped on
  // `match_label`, which the server sets to the gap each result
  // was searched for - so the pairing is carried rather than
  // guessed at by matching text.
  const gaps = useMemo(() => {
    const want = turn.verdict?.missing ?? [];
    if (want.length === 0) return [];
    const offers = turn.shopping ?? [];
    return want.map((one) => ({
      want: one,
      shops: offers.filter((item) => item.match_label === one),
    }));
  }, [turn.verdict?.missing, turn.shopping]);

  // **What somebody typed, in a capsule on the right.**
  //
  // Short by nature - a question, not a paragraph - so a bubble suits
  // it, and right-alignment is what tells the two voices apart now
  // that only one of them is tinted.
  if (mine) {
    return (
      <View style={{ alignSelf: 'flex-end', maxWidth: '86%', gap: Spacing.one }}>
        <Byline who="You" at={turn.at} align="right" />
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={turn.text}
          accessibilityHint={
            onEdit || onForget
              ? 'Long press for edit and delete'
              : undefined
          }
          animateEntrance={false}
          scale={0.99}
          onLongPress={() => {
            if (!onEdit && !onForget) return;
            void tapFeedback();
            setShowActions((was) => !was);
          }}
          style={{
            alignSelf: 'flex-end',
            paddingHorizontal: Spacing.three,
            paddingVertical: Spacing.two,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            backgroundColor: colors.accent,
          }}>
        {/* What went up with the question, inside the question.

            It used to sit as a card above the composer and stay
            there, so a thread four questions long still showed one
            pin pinned to the box - which read as "everything you
            ask is about this", when the model has the conversation
            and needs nothing re-sent. Here it is part of the turn it
            belonged to, and the composer is free. */}
        {turn.shownWith ? (
          <Image
            source={{ uri: turn.shownWith }}
            style={{
              width: '100%',
              aspectRatio: 3 / 4,
              maxHeight: 180,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              marginBottom: Spacing.two,
            }}
            contentFit="cover"
            transition={120}
            accessibilityLabel="The picture you asked about"
          />
        ) : null}
          <ThemedText
            selectable
            type="small"
            style={{ fontSize: FontSize.subhead, color: colors.accentText }}>
            {turn.text}
          </ThemedText>
        </MotionPressable>

        {/* Take it back, or say it differently.

            **Behind a long press, not under every message.** Two
            links beneath each question is a row of furniture down
            the whole thread, repeated for something people do
            rarely. A long press is the platform's own gesture for
            "what can I do with this", and it costs nothing until it
            is used.

            Both act on the question *and* what it produced: a reply
            left under a deleted question answers nothing, and an
            edited question whose old answer still sits below it reads
            as the stylist replying to something nobody asked. */}
        {showActions ? (
          <View
            style={{
              flexDirection: 'row',
              justifyContent: 'flex-end',
              gap: Spacing.three,
            }}>
            {onEdit ? (
              <Quiet
                label="Edit"
                onPress={() => {
                  setShowActions(false);
                  onEdit(turn);
                }}
              />
            ) : null}
            {onForget ? (
              <Quiet
                label="Delete"
                danger
                onPress={() => {
                  setShowActions(false);
                  onForget(turn);
                }}
              />
            ) : null}
            <Quiet label="Cancel" onPress={() => setShowActions(false)} />
          </View>
        ) : null}
      </View>
    );
  }

  return (
    <View style={{ alignSelf: 'stretch', gap: Spacing.two }}>
      {/* Who is speaking, and when.

          A word rather than a glyph. The sparkle that stood here said
          nothing a person could read, and three of them down a thread
          read as decoration - which is what they were. A byline is
          the convention for exactly this and costs the same line. */}
      <Byline who={`${BRAND.name} AI`} at={turn.at} align="left" />

      {turn.streaming && !turn.text ? (
        <Thinking />
      ) : (
        <ThemedText
          selectable
          type="small"
          style={{
            fontSize: FontSize.subhead,
            // Prose, so it gets prose leading. At the default this was
            // set solid and read as a block of grey rather than as
            // sentences.
            lineHeight: Math.round(FontSize.subhead * 1.45),
            color: colors.text,
          }}>
          {turn.text}
        </ThemedText>
      )}

      {/* **One section, grouped by the piece.**

          These were two: a list of what was missing, then a flat
          list of twelve shop links underneath it. The links were in
          gap order but nothing said so, so "Amazon: Varsity Jacket"
          and "Light Wash Baggy Jeans - Tillys" sat in one column
          with no way to tell which belonged to what - and the piece
          names were printed twice, once as the list above and once
          inside every link's title.

          Each missing piece is a heading now, with the places that
          sell it under it. The gaps still show before any shop is
          found, because "you have no cream trousers" is useful on
          its own and arrives a second before the links do. */}
      {gaps.length > 0 ? (
        <View style={{ alignSelf: 'stretch', gap: Spacing.three }}>
          <ThemedText type="smallBold" style={{ fontSize: FontSize.subhead }}>
            What would do it
          </ThemedText>
          {gaps.map((gap) => (
            <View key={gap.want} style={{ gap: Spacing.half }}>
              <ThemedText
                type="smallBold"
                style={{ fontSize: FontSize.footnote }}>
                {gap.want}
              </ThemedText>
              {gap.shops.length === 0 ? (
                <Line>Looking for somewhere to buy this</Line>
              ) : (
                gap.shops.map((item) => (
                  <Shoplink key={item.product_id} item={item} />
                ))
              )}
            </View>
          ))}
        </View>
      ) : null}

      {/* The nearby-shops button stood here.

          It asked a map which shops within a radius sell clothes,
          which is not the question: somebody wants *this jacket*,
          not *a jacket shop*, and three boutiques that do not stock
          it is a wrong answer delivered confidently. It was also a
          button that had to be found and pressed before it answered
          anything.

          Each gap now arrives with real places that sell it, looked
          up on the open web with the look as context - so there is
          nothing to press and nothing to wait for. See
          `domain/web_shopping`. */}

      {/* The picture, in the thread. */}
      {turn.renderId ? <Rendered render={render} /> : null}

      {/* **The look on a figure, drawn here, for nothing.**

          This used to send another question to the language model,
          which produced a prompt, which paid for an image, which
          took twenty to thirty seconds - to show somebody garments
          already sitting on their phone. The verdict names the
          garment ids and every one of them has a cut-out locally, so
          the figure is a composite: instant, free, and wearing the
          actual clothes rather than a model's impression of a
          description of them.

          `onTryOn` remains for the photorealistic version, which is
          a different question and is asked on the avatar screen. */}
      {wearing.length > 0 ? (
        worn ? (
          <View style={{ alignSelf: 'center', width: 240 }}>
            <OutfitFigure
              pieces={wearing}
              label="These of yours, on a figure"
            />
          </View>
        ) : (
          <Action label="See these on a figure" onPress={() => setWorn(true)} />
        )
      ) : null}
    </View>
  );
}

/**
 * The pause before the first word.
 *
 * It used to be the literal string "Thinking", which is a word sitting
 * still - and a reply can take several seconds to start, so a static
 * word is indistinguishable from a screen that has stopped. Three dots
 * rising in sequence say the same thing and say it continuously.
 *
 * **It loops, and that is allowed here.** WCAG 2.2.2 wants a control
 * for motion that runs past five seconds *beside other content*; a
 * busy indicator showing that a specific operation is still going is
 * the exception, and this one exists only while the request is open
 * and is replaced by the first token that arrives. It is also tiny and
 * carries no text, so there is nothing for it to compete with.
 */
function Thinking() {
  const colors = Colors[useScheme()];
  // The house helper, not a raw transition object: it collapses the
  // loop to nothing under Reduce Motion, which is what that setting
  // asks for - repetitive animation removed, not merely slowed.
  const timing = useMotiTiming();
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel="Thinking"
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.one,
        height: Spacing.three,
      }}>
      {[0, 1, 2].map((at) => (
        <MotiView
          key={at}
          // **Scale and fade together, not a jump.**
          //
          // The first version only moved the dots up and down, which
          // at three pixels reads as a twitch rather than as
          // thinking. Growing and brightening on the same curve gives
          // the group a visible travelling pulse at the same tiny
          // size, and the eye reads a pulse as "working" where it
          // reads a jitter as "broken".
          from={{ opacity: 0.2, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={timing({
            duration: 520,
            // Each dot a third of a cycle behind the last, so the
            // wave travels rather than three things blinking at once.
            delay: at * 170,
            loop: true,
            repeatReverse: true,
          })}
          style={{
            width: 7,
            height: 7,
            borderRadius: 4,
            backgroundColor: colors.accent,
          }}
        />
      ))}
    </View>
  );
}

function Line({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      selectable
      type="small"
      themeColor="textSecondary"
      style={{
        fontSize: FontSize.subhead,
        lineHeight: Math.round(FontSize.subhead * 1.45),
      }}>
      {children}
    </ThemedText>
  );
}

/**
 * Who said it, and when.
 *
 * One line, quiet, above every turn. Without it the two voices are
 * told apart only by alignment and a tint, which is enough while a
 * thread is short and stops being enough the moment it is scrolled
 * back through.
 */
function Byline({
  who,
  at,
  align,
}: {
  who: string;
  at?: number;
  align: 'left' | 'right';
}) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'baseline',
        gap: Spacing.two,
        justifyContent: align === 'right' ? 'flex-end' : 'flex-start',
      }}>
      <ThemedText
        type="smallBold"
        themeColor="textSecondary"
        style={{ fontSize: FontSize.meta }}>
        {who}
      </ThemedText>
      {at ? (
        <ThemedText
          themeColor="textSecondary"
          style={{ fontSize: FontSize.meta, fontVariant: ['tabular-nums'] }}>
          {clockOf(at)}
        </ThemedText>
      ) : null}
    </View>
  );
}

/** `21:03`. The phone's own 12/24-hour preference is honoured. */
export function clockOf(at: number): string {
  try {
    return new Date(at).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

/**
 * One place that sells a missing piece.
 *
 * The shop's own domain carries the trust - somebody knows what
 * `nordstrom.com` is and has never heard of a product id - so it is
 * the bold half, with the listing's title under it. Opening in the
 * system browser rather than a WebView: this is somebody's shopping,
 * and it belongs where their logins and payment details already are.
 */
function Shoplink({
  item,
}: {
  item: { title: string | null; retailer: string | null; url: string | null };
}) {
  const colors = Colors[useScheme()];
  const url = item.url;
  const label = item.title ?? 'A match';
  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={`${label}${item.retailer ? ` at ${item.retailer}` : ''}`}
      accessibilityHint={url ? 'Opens the shop in your browser' : undefined}
      accessibilityState={{ disabled: !url }}
      disabled={!url}
      animateEntrance={false}
      onPress={() => {
        if (!url) return;
        void tapFeedback();
        void Linking.openURL(url).catch(() => {
          // A link the phone cannot open is not worth an alert over
          // a suggestion. The row stays, and nothing happens.
        });
      }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
        // A row somebody is meant to tap needs to be tappable-sized,
        // not text-sized.
        minHeight: TapTarget,
        paddingVertical: Spacing.half,
      }}>
      <View style={{ flex: 1, gap: Spacing.half }}>
        {item.retailer ? (
          <ThemedText type="smallBold" style={{ fontSize: FontSize.subhead }}>
            {item.retailer}
          </ThemedText>
        ) : null}
        <ThemedText
          numberOfLines={2}
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.footnote }}>
          {label}
        </ThemedText>
      </View>
      {/* **It has to look like it opens something.**

          These were plain grey paragraphs, so nothing said they were
          links and nobody would have tried. A chevron is the
          platform's own mark for "this goes somewhere", and it is
          shown only when there is actually a URL - a row that cannot
          open must not advertise that it can. */}
      {url ? (
        <SymbolView
          name={{
            ios: 'arrow.up.right',
            android: 'open_in_new',
            web: 'open_in_new',
          }}
          size={13}
          tintColor={colors.textSecondary}
        />
      ) : null}
    </MotionPressable>
  );
}

/** A plain text action. Used for Edit and Delete under a question. */
function Quiet({
  label,
  onPress,
  danger = false,
}: {
  label: string;
  onPress: () => void;
  danger?: boolean;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      // The row is short, so the target is widened rather than made
      // taller: a 44pt-tall band under every question would double
      // the height of the thread.
      hitSlop={{ top: 10, bottom: 10, left: 8, right: 8 }}
      style={{ paddingVertical: Spacing.half }}>
      <ThemedText
        style={{
          fontSize: FontSize.meta,
          color: danger ? colors.danger : colors.textSecondary,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}

/** A quiet pill. Every optional action under a reply is one of these. */
function Action({ label, onPress }: { label: string; onPress: () => void }) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      onPress={onPress}
      style={{
        alignSelf: 'flex-start',
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        borderRadius: Radius.full,
        borderCurve: 'continuous',
        borderWidth: 1,
        borderColor: colors.border,
      }}>
      <ThemedText type="smallBold" style={{ fontSize: FontSize.footnote }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}

/**
 * The outfit on a figure: the mannequin while it draws, then the
 * picture.
 *
 * Reserved at the shape the app draws everything in, so the thread
 * does not jump when the picture lands - the same reason every other
 * surface here reserves space before it has one. What fills the
 * reservation is the difference: a mannequin standing in the frame,
 * dimmed, rather than an empty grey card.
 */
function Rendered({ render }: { render?: RenderLike }) {
  const colors = Colors[useScheme()];
  const [big, setBig] = useState(false);

  // **It said why, or it says why it cannot.**
  //
  // This used to be a spinner and nothing else, watching a render
  // nobody was polling - so a try-on that had already failed
  // ("create your avatar first") turned for ever. Somebody waiting
  // on a picture that is never coming is the worst state this
  // screen can be in.
  if (render?.state === 'failed') {
    return (
      <View
        style={{
          padding: Spacing.three,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
          gap: Spacing.one,
        }}>
        <ThemedText type="smallBold">I could not draw that</ThemedText>
        <ThemedText
          selectable
          type="small"
          themeColor="textSecondary"
          style={labelType(FontSize.footnote, 400)}>
          {render.error ?? 'Something went wrong drawing it.'}
        </ThemedText>
      </View>
    );
  }

  const frame = {
    width: 240,
    aspectRatio: 3 / 4,
    borderRadius: Radius.md,
    borderCurve: 'continuous' as const,
    overflow: 'hidden' as const,
    backgroundColor: colors.backgroundElement,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  };

  return (
    // Centred. It sat hard against the left margin under a paragraph
    // that ran the full width, which left a tall empty column beside
    // it and made the picture look like an attachment rather than
    // the answer.
    <View style={{ alignSelf: 'center', alignItems: 'center' }}>
      <MotionPressable
        accessibilityRole="imagebutton"
        accessibilityLabel={
          render?.uri ? 'The outfit, worn. Opens it full screen.' : 'Dressing the figure'
        }
        accessibilityState={{ disabled: !render?.uri }}
        disabled={!render?.uri}
        animateEntrance={false}
        scale={0.98}
        onPress={() => {
          void tapFeedback();
          setBig(true);
        }}
        style={frame}>
        {render?.uri ? (
          <Image
            source={{ uri: render.uri }}
            style={{ width: '100%', height: '100%' }}
            contentFit="cover"
            transition={160}
          />
        ) : (
          <>
            {/* The mannequin, standing in.

                At 0.3 it was invisible: these figures are pale on a
                pale ground, laid over a pale card. Full strength with
                a scrim over it reads as a figure waiting to be
                dressed, which is what it is. */}
            <Image
              source={STAND_IN}
              style={{ position: 'absolute', width: '100%', height: '100%' }}
              contentFit="cover"
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
            />
            <View
              style={{
                position: 'absolute',
                width: '100%',
                height: '100%',
                backgroundColor: colors.background,
                opacity: 0.55,
              }}
            />
            <View style={{ alignItems: 'center', gap: Spacing.two }}>
              <ActivityIndicator color={colors.accent} />
              <ThemedText type="smallBold" style={{ fontSize: FontSize.footnote }}>
                Dressing the figure
              </ThemedText>
            </View>
          </>
        )}
      </MotionPressable>

      {/* Full screen, with the things you can do to a picture.

          A render used to be a 240pt thumbnail and nothing else: no
          way to look at it properly and no way to keep it. */}
      <Modal
        visible={big && Boolean(render?.uri)}
        animationType="fade"
        onRequestClose={() => setBig(false)}>
        <View style={{ flex: 1, backgroundColor: '#000' }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Close"
            onPress={() => setBig(false)}
            style={{ flex: 1 }}>
            <Image
              source={{ uri: render?.uri ?? '' }}
              style={{ flex: 1 }}
              contentFit="contain"
              accessibilityLabel="The outfit, worn"
            />
          </Pressable>
          <View style={{ padding: Spacing.three }}>
            <PictureActions
              uri={render?.uri ?? ''}
              on="dark"
              onLeave={() => setBig(false)}
            />
          </View>
        </View>
      </Modal>
    </View>
  );
}
