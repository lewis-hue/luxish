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
 * **Everything the stylist produces is a turn, including a picture.**
 * An avatar wearing an outfit is the answer to "show me that on me",
 * so it sits in the thread beside the sentence that led to it rather
 * than in a panel of its own - which is what lets somebody look at
 * it and then keep talking.
 *
 * The composer is not here. It belongs below this, pinned, so the
 * newest reply is the thing nearest the thumb and the box does not
 * push the conversation off the screen as it grows.
 */

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
  /** Ask for this turn's outfit on their avatar. */
  onTryOn: (turn: Turn) => void;
  /** Offered under the last reply that found nothing they own. */
  shops?: ShopsState;
  /** Every avatar in flight or finished, polled elsewhere. */
  renders?: readonly RenderLike[];
}) {
  if (turns.length === 0) return null;
  const lastGap = lastWithoutAMatch(turns);
  return (
    <View style={{ gap: Spacing.three }}>
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

  return (
    <View
      style={{
        alignSelf: mine ? 'flex-end' : 'flex-start',
        maxWidth: '88%',
        gap: Spacing.two,
      }}>
      <View
        style={{
          flexDirection: 'row',
          gap: Spacing.two,
          padding: Spacing.three,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: mine ? colors.accent : colors.backgroundElement,
        }}>
        {!mine ? (
          <SymbolView
            name={{
              ios: 'sparkles',
              android: 'auto_awesome',
              web: 'auto_awesome',
            }}
            size={16}
            tintColor={colors.accent}
          />
        ) : null}
        <ThemedText
          selectable
          type="small"
          style={{
            flex: 1,
            fontSize: FontSize.subhead,
            color: mine ? colors.accentText : colors.text,
          }}>
          {turn.text}
          {turn.streaming && !turn.text ? 'Thinking' : ''}
        </ThemedText>
      </View>

      {/* What they would need to buy, named before any shop is
          searched: "you have no cream trousers" is useful on its own
          and arrives a second before the offers do. */}
      {turn.verdict && !turn.verdict.hasMatch && turn.verdict.missing.length ? (
        <View style={{ gap: Spacing.half, paddingHorizontal: Spacing.two }}>
          <ThemedText type="smallBold">What would do it</ThemedText>
          {turn.verdict.missing.map((want) => (
            <ThemedText
              key={want}
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              {want}
            </ThemedText>
          ))}
        </View>
      ) : null}

      {turn.shopping?.length ? (
        <View style={{ gap: Spacing.half, paddingHorizontal: Spacing.two }}>
          <ThemedText type="smallBold">Where to get them</ThemedText>
          {turn.shopping.map((item) => (
            <ThemedText
              key={item.product_id}
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              {item.title ?? 'A match'}
              {item.retailer ? ` - ${item.retailer}` : ''}
            </ThemedText>
          ))}
        </View>
      ) : null}

      {/* **Somewhere to actually go**, when they own nothing that
          works. A lookup upstream takes between two and forty-five
          seconds, so it is never part of the reply's own stream -
          it is a button under the answer that already arrived. */}
      {shops ? (
        <View style={{ gap: Spacing.half, paddingHorizontal: Spacing.two }}>
          {!shops.items && !shops.looking ? (
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel="Find shops near me"
              animateEntrance={false}
              onPress={() => {
                void tapFeedback();
                shops.find();
              }}
              style={{
                alignSelf: 'flex-start',
                paddingHorizontal: Spacing.three,
                paddingVertical: Spacing.two,
                borderRadius: Radius.full,
                borderCurve: 'continuous',
                borderWidth: 1,
                borderColor: colors.border,
              }}>
              <ThemedText type="smallBold">Find shops near me</ThemedText>
            </MotionPressable>
          ) : null}

          {shops.looking ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              Looking for shops near you
            </ThemedText>
          ) : null}

          {shops.items?.length ? (
            <>
              <ThemedText type="smallBold">Shops near you</ThemedText>
              {shops.items.slice(0, 6).map((shop) => (
                <ThemedText
                  key={shop.name}
                  type="small"
                  themeColor="textSecondary"
                  style={labelType(FontSize.footnote, 400)}>
                  {shop.name}
                  {shop.distanceM !== null ? ` - ${howFar(shop.distanceM)}` : ''}
                </ThemedText>
              ))}
              {/* Required wherever this data is shown. */}
              {shops.attribution ? (
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={labelType(FontSize.footnote, 400)}>
                  {shops.attribution}
                </ThemedText>
              ) : null}
            </>
          ) : null}

          {shops.note ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              {shops.note}
            </ThemedText>
          ) : null}
        </View>
      ) : null}

      {/* The picture, in the thread. */}
      {turn.renderId ? <Rendered render={render} /> : null}

      {/* Offered rather than done automatically: drawing an avatar is
          a paid call and twenty seconds, and not every answer is one
          somebody wants to see on themselves. */}
      {canTryOn(turn) ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="See this on me"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            onTryOn(turn);
          }}
          style={{
            alignSelf: 'flex-start',
            paddingHorizontal: Spacing.three,
            paddingVertical: Spacing.two,
            borderRadius: Radius.full,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.border,
          }}>
          <ThemedText type="smallBold">See this on me</ThemedText>
        </MotionPressable>
      ) : null}
    </View>
  );
}

/**
 * The avatar for one turn: a placeholder while it draws, then the
 * picture.
 *
 * Reserved at the shape the app draws everything in, so the thread
 * does not jump when the picture lands - the same reason every other
 * surface here reserves space before it has one.
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
        width: 180,
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
          accessibilityLabel="You, in this outfit"
        />
      ) : (
        <View style={{ alignItems: 'center', gap: Spacing.two }}>
          <ActivityIndicator color={colors.accent} />
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={labelType(FontSize.footnote, 400)}>
            Drawing this on you
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
      )}
    </View>
  );
}
