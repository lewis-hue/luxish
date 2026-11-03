import * as Clipboard from 'expo-clipboard';
import { File } from 'expo-file-system';
import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import { Modal, ScrollView, View, useWindowDimensions } from 'react-native';
import {
  Gesture,
  GestureDetector,
  GestureHandlerRootView,
} from 'react-native-gesture-handler';
import Animated, {
  type SharedValue,
  Easing,
  Extrapolation,
  interpolate,
  runOnJS,
  runOnUI,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { type FeedFit } from '@/api/queries/discover-feed';
import { ThemedText } from '@/components/themed-text';
import {
  MotionPressable,
  successFeedback,
  tapFeedback,
} from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  ImageFade,
  Motion,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { intoColumns } from '@/features/feed/columns';
import { surroundOpacity } from '@/features/feed/zoom';
import { Zoomable } from '@/features/feed/zoomable';
import { FitCard } from '@/features/feed/fit-card';
import { useScheme } from '@/hooks/use-theme';

/** Where the shelf rests between its two ends, as a share of the screen. */
const REST = 0.62;

/** How much of the shelf stays on screen when it is all the way down. */
const HINT = 76;

/** Past this, a drag is a throw and goes to the next stop in its direction. */
const THROWN = 450;

/**
 * How it settles, however it is moved.
 *
 * Timing, not a spring. A spring overshoots by design, and on a
 * surface the size of the screen that reads as the shelf wobbling
 * rather than as a flourish: it goes up when pushed up, down when
 * pulled down, and stops where it arrives.
 */
const SETTLE = { duration: Motion.base, easing: Easing.out(Easing.cubic) };

function slideTo(value: SharedValue<number>, to: number) {
  'worklet';
  value.value = withTiming(to, SETTLE);
}

/**
 * The photograph, at the size of the screen, with what looks like it
 * on a shelf over the bottom of it.
 *
 * **Three stops, and the picture is the point of all of them.** All
 * the way down, the shelf is one line of type saying it is there and
 * the photograph has the whole screen. At rest it covers the bottom
 * third. All the way up it is a grid, and the picture it came from
 * shrinks to a thumbnail in the bar — which is also the way back,
 * because a full-screen grid whose only exit is a drag is a screen
 * people get stuck on.
 *
 * **It slides over the picture, not under it.** Everywhere else in
 * this app more pictures sit *below* the one being looked at, which
 * means scrolling away from it to see them. Here the photograph stays
 * where it is and the alternatives come to meet it.
 *
 * **The picture is decoded once, at full size.** `expo-image`
 * downsamples to the frame it first measures, so a photograph that
 * starts behind a shelf and then has the shelf pulled off it would be
 * an upscale of a smaller decode — soft, and exactly when somebody
 * has asked to look closer.
 *
 * **Hold the picture to copy it.** Sharing sends a link to the fit,
 * which is the right default and the wrong thing when somebody wants
 * the picture itself in a message.
 */
export function PhotoView({
  uri,
  fit,
  more,
  visible,
  onClose,
  onOpenFit,
  onMore,
  onShare,
}: {
  uri: string | null;
  fit: FeedFit;
  /** Fits that look like this one, closest first. */
  more: readonly FeedFit[];
  visible: boolean;
  onClose: () => void;
  onOpenFit: (id: string) => void;
  onMore: () => void;
  onShare: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const [copied, setCopied] = useState<string | null>(null);

  /**
   * How far into the picture somebody has pinched.
   *
   * The shelf and the chrome fade with it: a sheet of other pins
   * sitting over a photograph somebody has just zoomed into is the
   * thing they were trying to get away from.
   */
  const zoom = useSharedValue(1);
  const surround = useAnimatedStyle(() => ({
    opacity: surroundOpacity(zoom.value),
  }));

  const up = 0;
  const rest = height * REST;
  const down = height - HINT - insets.bottom;

  const top = useSharedValue(rest);
  const start = useSharedValue(rest);
  /**
   * Which stop it settled at, in React.
   *
   * The bar at the top of the shelf is three different things, and
   * which one it is cannot be decided on the UI thread.
   */
  const [stop, setStop] = useState<'up' | 'rest' | 'down'>('rest');

  const drag = Gesture.Pan()
    .onStart(() => {
      start.value = top.value;
    })
    .onUpdate((event) => {
      // Bounded by the two ends, with no rubber band: this is a shelf,
      // not a scroll view, and letting it fly past either end would
      // mean it could be left somewhere that is neither.
      top.value = Math.min(down, Math.max(up, start.value + event.translationY));
    })
    .onEnd((event) => {
      const stops = [up, rest, down];
      const here = top.value;
      let settled: number;
      if (event.velocityY < -THROWN) {
        // Thrown: the next stop in that direction. A flick is the
        // gesture people actually make, and making them drag the whole
        // way is what makes a sheet feel stuck.
        settled = here > rest ? rest : up;
      } else if (event.velocityY > THROWN) {
        settled = here < rest ? rest : down;
      } else {
        settled = stops.reduce((best, point) =>
          Math.abs(point - here) < Math.abs(best - here) ? point : best,
        );
      }
      top.value = withTiming(settled, SETTLE);
      runOnJS(setStop)(
        settled === up ? 'up' : settled === down ? 'down' : 'rest',
      );
    });

  const settle = (to: number) => {
    runOnUI(slideTo)(top, to);
    setStop(to === up ? 'up' : to === down ? 'down' : 'rest');
  };

  const sheet = useAnimatedStyle(() => ({
    transform: [{ translateY: top.value }],
  }));
  // The bar makes room for the status bar as it arrives at the top,
  // rather than jumping by an inset the moment it lands.
  const bar = useAnimatedStyle(() => ({
    paddingTop: interpolate(
      top.value,
      [up, rest],
      [insets.top, 0],
      Extrapolation.CLAMP,
    ),
  }));
  // The chips over the photograph go as the shelf covers them.
  const chips = useAnimatedStyle(() => ({
    opacity: interpolate(top.value, [up, rest], [0, 1], Extrapolation.CLAMP),
  }));

  const column = (width - Spacing.two * 2 - Spacing.two) / 2;

  /**
   * The picture onto the clipboard, as bytes rather than a path.
   *
   * A file URI is useless in another app: the cache directory is this
   * app's and nothing else can read it. The bytes are what somebody
   * means by "copy the image".
   */
  const copy = async () => {
    if (!uri) return;
    void tapFeedback();
    try {
      const base64 = await new File(uri).base64();
      await Clipboard.setImageAsync(base64);
      void successFeedback();
      setCopied('Copied. Paste it wherever you like.');
    } catch {
      setCopied('That picture could not be copied.');
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent>
      <GestureHandlerRootView style={{ flex: 1 }}>
        <View style={{ flex: 1, backgroundColor: colors.backgroundElement }}>
          {uri ? (
            // **Pinchable, which is what makes `cover` honest.**
            // The picture fills the screen and the fill crops; this
            // is how somebody gets back what it took. The frame is
            // the whole screen, so that is what bounds the pan.
            <Zoomable
              scale={zoom}
              width={width}
              height={height}
              style={{ position: 'absolute', width, height }}>
            <MotionPressable
              accessibilityRole="image"
              accessibilityLabel={fit.caption ?? `A fit by ${fit.authorName}`}
              accessibilityHint="Hold to copy this picture"
              animateEntrance={false}
              animatePress={false}
              onLongPress={() => void copy()}
              // The whole screen, behind the shelf.
              style={{ position: 'absolute', width, height }}>
              <Image
                source={{ uri }}
                // **`cover`: this screen is the picture, edge to edge.**
                //
                // It has been both. `cover` first, then `contain`
                // when the fit page began cropping - on the argument
                // that somewhere had to show the photograph whole,
                // and in a fashion app the bottom of a full-length
                // shot is the shoes. That was right about the need
                // and wrong about the remedy: a near-square picture
                // in a tall frame came out as a band of grey, a
                // strip of photograph and a band of grey, which is
                // not a full-screen view of anything.
                //
                // Pinch answers it properly. The picture fills the
                // screen as it should, and what the fill crops is a
                // gesture away rather than a redesign away.
                contentFit="cover"
                transition={ImageFade}
                // Decoded at its own resolution, not at the frame's.
                // The shelf slides over this picture and off it again;
                // a decode sized to the first frame would be upscaled
                // the moment somebody asked to see more of it.
                allowDownscaling={false}
                cachePolicy="memory-disk"
                priority="high"
                style={{ width: '100%', height: '100%' }}
              />
            </MotionPressable>
            </Zoomable>
          ) : null}

          <Animated.View
            pointerEvents="box-none"
            style={[
              {
                position: 'absolute',
                top: insets.top + Spacing.two,
                left: Spacing.three,
                right: Spacing.three,
                flexDirection: 'row',
                justifyContent: 'space-between',
              },
              chips,
              // Out of the way while the picture is being pinched.
              surround,
            ]}>
            <Chip
              label="Close"
              icon={{ ios: 'xmark', android: 'close', web: 'close' }}
              onPress={onClose}
            />
            <View style={{ flexDirection: 'row', gap: Spacing.two }}>
              {/* Sharing is the thing most often wanted from a picture
                  at this size, so it stands beside the menu rather
                  than inside it. */}
              <Chip
                label="Share this fit"
                icon={{
                  ios: 'arrow.up.right',
                  android: 'arrow_outward',
                  web: 'arrow_outward',
                }}
                onPress={onShare}
              />
              <Chip
                label="More"
                icon={{
                  ios: 'ellipsis',
                  android: 'more_horiz',
                  web: 'more_horiz',
                }}
                onPress={onMore}
              />
            </View>
          </Animated.View>

          {copied ? (
            <View
              pointerEvents="none"
              style={{
                position: 'absolute',
                left: Spacing.three,
                right: Spacing.three,
                top: insets.top + TapTarget + Spacing.four,
                padding: Spacing.two,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                backgroundColor: colors.text,
              }}>
              <ThemedText
                accessibilityLiveRegion="polite"
                style={{
                  ...labelType(FontSize.subhead, 400),
                  color: colors.background,
                  textAlign: 'center',
                }}>
                {copied}
              </ThemedText>
            </View>
          ) : null}

          {/* The shelf. Absolute and full height, moved by its own
              offset, so raising it never relayouts the picture.

              It fades with the zoom: a sheet of other pins sitting
              over a photograph somebody has just pinched into is
              the thing they were trying to get away from. */}
          <Animated.View
            style={[
              surround,
              {
                position: 'absolute',
                left: 0,
                right: 0,
                top: 0,
                height,
                borderTopLeftRadius: Radius.lg,
                borderTopRightRadius: Radius.lg,
                borderCurve: 'continuous',
                // Out of the way means out of the way: at the bottom
                // stop the only thing over the photograph is the line
                // of type on its own scrim.
                backgroundColor:
                  stop === 'down' ? 'transparent' : colors.background,
                boxShadow:
                  stop === 'down'
                    ? undefined
                    : '0 -8px 24px rgba(0, 0, 0, 0.16)',
              },
              sheet,
            ]}>
            {/* Only the bar takes the drag. The grid scrolls on its
                own, and one gesture owning both is where a sheet
                starts fighting the list inside it. */}
            <GestureDetector gesture={drag}>
              <Animated.View
                accessibilityRole="adjustable"
                accessibilityLabel="Fits like this one"
                accessibilityHint="Drag up for more, down to go back to the picture"
                style={[{ justifyContent: 'center' }, bar]}>
                {stop === 'up' ? (
                  /* Covering the picture, so the bar carries the way
                     back to it: a chevron, the picture itself at
                     thumbnail size, and the same menu. */
                  <View
                    style={{
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: Spacing.three,
                      height: TapTarget + Spacing.two,
                      paddingHorizontal: Spacing.three,
                    }}>
                    <MotionPressable
                      accessibilityRole="button"
                      accessibilityLabel="Back to the picture"
                      animateEntrance={false}
                      scale={0.92}
                      hitSlop={8}
                      onPress={() => {
                        void tapFeedback();
                        settle(rest);
                      }}>
                      <SymbolView
                        name={{
                          ios: 'chevron.down',
                          android: 'expand_more',
                          web: 'expand_more',
                        }}
                        size={22}
                        tintColor={colors.text}
                      />
                    </MotionPressable>

                    <View style={{ flex: 1, alignItems: 'center' }}>
                      {uri ? (
                        <MotionPressable
                          accessibilityRole="button"
                          accessibilityLabel="Back to the picture"
                          animateEntrance={false}
                          scale={0.94}
                          onPress={() => {
                            void tapFeedback();
                            settle(rest);
                          }}>
                          <Image
                            source={{ uri }}
                            contentFit="cover"
                            accessible={false}
                            style={{
                              width: 30,
                              height: 44,
                              borderRadius: Radius.sm,
                              borderCurve: 'continuous',
                            }}
                          />
                        </MotionPressable>
                      ) : null}
                    </View>

                    <MotionPressable
                      accessibilityRole="button"
                      accessibilityLabel="More"
                      animateEntrance={false}
                      scale={0.92}
                      hitSlop={8}
                      onPress={() => {
                        void tapFeedback();
                        onMore();
                      }}>
                      <SymbolView
                        name={{
                          ios: 'ellipsis',
                          android: 'more_horiz',
                          web: 'more_horiz',
                        }}
                        size={22}
                        tintColor={colors.text}
                      />
                    </MotionPressable>
                  </View>
                ) : stop === 'down' ? (
                  /* Out of the way, and saying so.

                     A handle alone at the bottom of a photograph is a
                     control nobody reads as one; the line of type is
                     what makes the gesture discoverable, and it sits
                     on the picture so the picture keeps the screen. */
                  <MotionPressable
                    accessibilityRole="button"
                    accessibilityLabel="Show fits like this one"
                    animateEntrance={false}
                    scale={0.98}
                    onPress={() => {
                      void tapFeedback();
                      settle(rest);
                    }}
                    style={{
                      height: HINT,
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: Spacing.two,
                      backgroundColor: '#00000066',
                    }}>
                    <ThemedText
                      style={{
                        ...labelType(FontSize.body, 400),
                        color: '#FFFFFF',
                      }}>
                      Swipe up to explore
                    </ThemedText>
                    <View
                      style={{
                        width: 120,
                        height: 5,
                        borderRadius: Radius.full,
                        backgroundColor: '#FFFFFF',
                      }}
                    />
                  </MotionPressable>
                ) : (
                  <View
                    style={{
                      height: TapTarget,
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                    <View
                      style={{
                        width: 40,
                        height: 5,
                        borderRadius: Radius.full,
                        backgroundColor: colors.border,
                      }}
                    />
                  </View>
                )}
              </Animated.View>
            </GestureDetector>

            <ScrollView
              showsVerticalScrollIndicator={false}
              contentContainerStyle={{
                paddingHorizontal: Spacing.two,
                paddingBottom: insets.bottom + Spacing.five,
              }}>
              {/* Two columns stacked independently, not wrapped rows.

                  `flexWrap` sized every wrapped row to its tallest
                  tile, so a short one left a band of white beneath it
                  and the gaps down one column looked nothing like the
                  gaps down the other. */}
              <View style={{ flexDirection: 'row', gap: Spacing.two }}>
                {intoColumns(more).map((lane, at) => (
                  <View key={at} style={{ flex: 1, gap: Spacing.two }}>
                    {lane.map((other) => (
                      <FitCard
                        key={other.id}
                        fit={other}
                        width={column}
                        // The screen that owns this decides when to
                        // close: it has to happen before the push, not
                        // with it.
                        onOpen={() => onOpenFit(other.id)}
                      />
                    ))}
                  </View>
                ))}
              </View>
              {more.length === 0 ? (
                <ThemedText
                  themeColor="textSecondary"
                  style={{
                    padding: Spacing.three,
                    ...labelType(FontSize.subhead, 400),
                  }}>
                  Nothing here looks like this one yet.
                </ThemedText>
              ) : null}
            </ScrollView>
          </Animated.View>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

/** One floating control over the photograph. */
function Chip({
  label,
  icon,
  onPress,
}: {
  label: string;
  icon: Parameters<typeof SymbolView>[0]['name'];
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
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: colors.background,
        opacity: 0.92,
      }}>
      <SymbolView name={icon} size={18} tintColor={colors.text} />
    </MotionPressable>
  );
}
