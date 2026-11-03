import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { ActivityIndicator, View } from 'react-native';

import { howFar } from '@/api/queries/shops';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  labelType,
} from '@/constants/theme';
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
}: {
  turns: readonly Turn[];
  /** Ask for this turn's outfit on the figure. */
  onTryOn: (turn: Turn) => void;
  /** Offered under the last reply that found nothing they own. */
  shops?: ShopsState;
  /** Every figure in flight or finished, polled elsewhere. */
  renders?: readonly RenderLike[];
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
}: {
  turn: Turn;
  onTryOn: (turn: Turn) => void;
  shops?: ShopsState;
  render?: RenderLike;
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
      <View
        style={{
          alignSelf: 'flex-end',
          maxWidth: '82%',
          paddingHorizontal: Spacing.three,
          paddingVertical: Spacing.two,
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          backgroundColor: colors.accent,
        }}>
        <ThemedText
          selectable
          type="small"
          style={{ fontSize: FontSize.subhead, color: colors.accentText }}>
          {turn.text}
        </ThemedText>
      </View>
    );
  }

  return (
    <View style={{ alignSelf: 'stretch', gap: Spacing.two }}>
      {/* The mark, on its own line above the answer.

          It was inline, first in a flex row with the text second. That
          is what made the reply a two-column layout and cost it the
          width it needed; above the text it costs one short line and
          the paragraph gets the full measure. */}
      <SymbolView
        name={{ ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }}
        size={15}
        tintColor={colors.accent}
        style={{ width: 15, height: 15 }}
      />

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
        {turn.streaming && !turn.text ? 'Thinking' : ''}
      </ThemedText>

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

          {shops.looking ? <Line>Looking for shops near you</Line> : null}

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

          {shops.note ? <Line>{shops.note}</Line> : null}
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
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        gap: Spacing.half,
        paddingLeft: Spacing.three,
        borderLeftWidth: 1,
        borderLeftColor: colors.border,
      }}>
      <ThemedText type="smallBold" style={{ fontSize: FontSize.footnote }}>
        {title}
      </ThemedText>
      {children}
    </View>
  );
}

function Line({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      type="small"
      themeColor="textSecondary"
      style={labelType(FontSize.footnote, 400)}>
      {children}
    </ThemedText>
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

  return (
    <View
      style={{
        // Wider than the 180 it was. A figure in an outfit is the
        // thing being judged, and at 180 the clothes were too small
        // to judge.
        width: 220,
        aspectRatio: 3 / 4,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      {render?.uri ? (
        <Image
          source={{ uri: render.uri }}
          style={{ width: '100%', height: '100%' }}
          contentFit="cover"
          transition={160}
          accessibilityLabel="The outfit, worn"
        />
      ) : (
        <>
          {/* The mannequin, held back so it reads as a placeholder
              rather than as the finished picture. */}
          <Image
            source={STAND_IN}
            style={{
              position: 'absolute',
              width: '100%',
              height: '100%',
              opacity: 0.3,
            }}
            contentFit="cover"
            // Decorative: the label below says what is happening.
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
          />
          <View style={{ alignItems: 'center', gap: Spacing.two }}>
            <ActivityIndicator color={colors.accent} />
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              Dressing the figure
            </ThemedText>
            {/* Said out loud, because a picture takes about half a
                minute and a wheel with no number beside it reads as
                stuck long before it is. */}
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              about 30 seconds
            </ThemedText>
          </View>
        </>
      )}
    </View>
  );
}
