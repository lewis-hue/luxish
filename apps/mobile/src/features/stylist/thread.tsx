import { Image } from 'expo-image';
import { MotiView } from 'moti';
import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, View } from 'react-native';

import { howFar } from '@/api/queries/shops';
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
  labelType,
} from '@/constants/theme';
import { BRAND } from '@/branding';
import { PictureActions } from '@/features/avatar/picture-actions';
import { canTryOn, type Turn } from '@/features/stylist/conversation';
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

export interface ShopsState {
  /** Null until somebody asks. */
  items: { name: string; distanceM: number | null }[] | null;
  attribution: string | null;
  note: string | null;
  looking: boolean;
  find: () => void;
}

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
  shops,
  renders = [],
  onEdit,
  onForget,
}: {
  turns: readonly Turn[];
  /** Ask for this turn's outfit on the figure. */
  onTryOn: (turn: Turn) => void;
  /** Offered under the last reply that found nothing they own. */
  shops?: ShopsState;
  /** Every figure in flight or finished, polled elsewhere. */
  renders?: readonly RenderLike[];
  /** Take a question back into the composer to ask it differently. */
  onEdit?: (turn: Turn) => void;
  /** Remove a question and the answer it produced. */
  onForget?: (turn: Turn) => void;
}) {
  if (turns.length === 0) return null;
  const lastGap = lastWithoutAMatch(turns);
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
          shops={turn.id === lastGap ? shops : undefined}
          render={
            turn.renderId
              ? renders.find((r) => r.id === turn.renderId)
              : undefined
          }
          onEdit={onEdit}
          onForget={onForget}
        />
      ))}
    </View>
  );
}

function lastWithoutAMatch(turns: readonly Turn[]): string | null {
  for (let at = turns.length - 1; at >= 0; at -= 1) {
    const turn = turns[at];
    if (turn.who !== 'stylist' || turn.streaming || !turn.verdict) continue;
    return turn.verdict.hasMatch ? null : turn.id;
  }
  return null;
}

function Bubble({
  turn,
  onTryOn,
  shops,
  render,
  onEdit,
  onForget,
}: {
  turn: Turn;
  onTryOn: (turn: Turn) => void;
  shops?: ShopsState;
  render?: RenderLike;
  onEdit?: (turn: Turn) => void;
  onForget?: (turn: Turn) => void;
}) {
  const colors = Colors[useScheme()];
  const mine = turn.who === 'you';

  // **What somebody typed, in a capsule on the right.**
  //
  // Short by nature - a question, not a paragraph - so a bubble suits
  // it, and right-alignment is what tells the two voices apart now
  // that only one of them is tinted.
  if (mine) {
    return (
      <View style={{ alignSelf: 'flex-end', maxWidth: '86%', gap: Spacing.one }}>
        <Byline who="You" at={turn.at} align="right" />
        <View
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
        </View>

        {/* Take it back, or say it differently.

            Both act on the question *and* what it produced: a reply
            left under a deleted question answers nothing, and an
            edited question whose old answer still sits below it reads
            as the stylist replying to something nobody asked. */}
        {onEdit || onForget ? (
          <View
            style={{
              flexDirection: 'row',
              justifyContent: 'flex-end',
              gap: Spacing.three,
            }}>
            {onEdit ? (
              <Quiet label="Edit" onPress={() => onEdit(turn)} />
            ) : null}
            {onForget ? (
              <Quiet label="Delete" onPress={() => onForget(turn)} danger />
            ) : null}
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

      {/* What they would need to buy, named before any shop is
          searched: "you have no cream trousers" is useful on its own
          and arrives a second before the offers do. */}
      {turn.verdict && !turn.verdict.hasMatch && turn.verdict.missing.length ? (
        <Listing title="What would do it">
          {turn.verdict.missing.map((want) => (
            <Line key={want}>{want}</Line>
          ))}
        </Listing>
      ) : null}

      {turn.shopping?.length ? (
        <Listing title="Where to get them">
          {turn.shopping.map((item) => (
            <Line key={item.product_id}>
              {item.title ?? 'A match'}
              {item.retailer ? ` - ${item.retailer}` : ''}
            </Line>
          ))}
        </Listing>
      ) : null}

      {/* **Somewhere to actually go**, when they own nothing that
          works. A lookup upstream takes between two and forty-five
          seconds, so it is never part of the reply's own stream -
          it is a button under the answer that already arrived. */}
      {shops ? (
        <View style={{ gap: Spacing.one }}>
          {!shops.items && !shops.looking ? (
            <Action
              label="Find shops near me"
              onPress={() => {
                void tapFeedback();
                shops.find();
              }}
            />
          ) : null}

          {/* The tap has to show immediately that it landed.

              A lookup runs through a permission prompt and then a
              directory that can take forty-five seconds, so without
              this the button sat there looking ignored - which is
              exactly how it was reported: "I click it and nothing
              happens". A spinner beside the words says the opposite. */}
          {shops.looking ? (
            <View
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                gap: Spacing.two,
              }}>
              <ActivityIndicator size="small" color={colors.accent} />
              <Line>Looking for shops near you</Line>
            </View>
          ) : null}

          {shops.items?.length ? (
            <Listing title="Shops near you">
              {shops.items.slice(0, 6).map((shop) => (
                <Line key={shop.name}>
                  {shop.name}
                  {shop.distanceM !== null ? ` - ${howFar(shop.distanceM)}` : ''}
                </Line>
              ))}
              {/* Required wherever this data is shown. */}
              {shops.attribution ? <Line>{shops.attribution}</Line> : null}
            </Listing>
          ) : null}

          {/* A note on its own is a dead end: "allow location and I
              can show shops near you" with no way to try again means
              granting it in Settings and then hunting for this button.
              The note and the retry travel together. */}
          {shops.note ? (
            <View style={{ gap: Spacing.one }}>
              <Line>{shops.note}</Line>
              {!shops.looking ? (
                <Action
                  label="Try again"
                  onPress={() => {
                    void tapFeedback();
                    shops.find();
                  }}
                />
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}

      {/* The picture, in the thread. */}
      {turn.renderId ? <Rendered render={render} /> : null}

      {/* Offered rather than done automatically: drawing a figure is
          a paid call and twenty seconds, and not every answer is one
          somebody wants to see worn. */}
      {canTryOn(turn) ? (
        <Action
          label="See this on the figure"
          onPress={() => {
            void tapFeedback();
            onTryOn(turn);
          }}
        />
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

/**
 * A short titled list under an answer.
 *
 * Indented by a hairline rather than by a heading and a gap: the rule
 * says "these belong to the sentence above" in one pixel, where a
 * second bold heading per list was starting to make every reply look
 * like a document.
 */
function Listing({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    // **Full measure, like the sentence above it.**
    //
    // This was indented behind a hairline at footnote size, which
    // squeezed "brown suede trucker jacket with shearling collar"
    // into a narrow column while the paragraph above it ran the full
    // width. It is part of the same answer and reads as one only if
    // it is set like one: same measure, same size, the heading doing
    // the separating that the rule was doing.
    <View style={{ alignSelf: 'stretch', gap: Spacing.one }}>
      <ThemedText type="smallBold" style={{ fontSize: FontSize.subhead }}>
        {title}
      </ThemedText>
      {children}
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
