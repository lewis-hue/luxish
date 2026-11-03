import { useEffect, useState } from 'react';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  runOnJS,
  useAnimatedReaction,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import type { StyleProp, ViewStyle } from 'react-native';

import { Motion } from '@/constants/theme';
import { clampPan, clampZoom, isZoomed } from '@/features/feed/zoom';

/**
 * Assign to a Reanimated shared value.
 *
 * The same indirection `components/ui/motion` uses, for the same
 * reason and with the same reasoning: `react-hooks/immutability`
 * treats `.value` as React-owned state and rejects an assignment
 * written inside a closure, where it cannot tell the closure only
 * ever runs from a gesture. A shared value is mutable by design and
 * driving it from a gesture is the documented pattern, so routing
 * the assignment through a plain function satisfies the rule
 * honestly rather than suppressing it.
 */
function write<T>(shared: SharedValue<T>, next: T): void {
  'worklet';
  shared.value = next;
}

/**
 * A picture somebody can pinch into, and the page behind it getting
 * out of the way.
 *
 * **The gesture is on the picture, not the screen.** Zooming a whole
 * page scales its buttons and its text with the photograph, which is
 * not what anybody is asking for when they pinch a picture. Only
 * what is inside this scales; everything around it stays the size it
 * was.
 *
 * **`scale` is shared, not reported.** The surrounding page fades as
 * the zoom goes in, and driving that from React state would mean a
 * round trip to the JavaScript thread on every frame of a pinch.
 * The caller passes a shared value in and reads it from its own
 * animated style, so the fade and the zoom are the same frame.
 *
 * **The zoom is kept after the pinch, and the picture can then be
 * moved.** That is the point of it: the shell crops a photograph to
 * one shape, and looking at what it cropped means pinching in and
 * then dragging around - which takes two hands if the zoom lasts
 * only as long as the fingers.
 *
 * **So the drag is arbitrated rather than avoided.** A zoomed
 * picture and the page behind it both want a vertical drag. While
 * the picture is larger than its frame the drag is the picture's
 * and the page does not scroll; at the fit there is nothing to move
 * and the page has it back. Double tap returns to the fit, which is
 * what makes keeping the zoom safe: without a way out, somebody
 * could be left on a page that will not scroll.
 */
export function Zoomable({
  scale,
  width,
  height,
  children,
  style,
  onZoomedChange,
}: {
  /** Shared with the caller, so a fade can be driven from the same frame. */
  scale: SharedValue<number>;
  /** The frame's size, which bounds how far the picture can travel. */
  width: number;
  height: number;
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  /**
   * Told when a pinch begins and ends.
   *
   * The one thing the page genuinely needs on the JavaScript thread:
   * a scroll view has to stop scrolling while somebody is dragging
   * a zoomed picture around inside it. Fires twice per pinch, not
   * once per frame.
   */
  onZoomedChange?: (zoomed: boolean) => void;
}) {
  const saved = useSharedValue(1);
  const x = useSharedValue(0);
  const y = useSharedValue(0);
  const savedX = useSharedValue(0);
  const savedY = useSharedValue(0);

  /**
   * Whether the picture is currently larger than its frame.
   *
   * **Held in React as well as on the UI thread, because a gesture
   * can only be enabled from React.** An inert pan is not the same
   * as an absent one: a `Pan` that activates and then does nothing
   * has still taken the touch, and the scroll view behind it never
   * sees the drag. That is what made the pins impossible to scroll
   * by - the whole picture was a dead zone.
   */
  const [zoomed, setZoomed] = useState(false);

  const tell = (next: boolean) => {
    setZoomed(next);
    onZoomedChange?.(next);
  };

  const settle = () => {
    'worklet';
    // Back to the fit, and back to the middle with it. Leaving a
    // picture at 1x but offset would show the frame down one side.
    write(scale, withTiming(1, { duration: Motion.base }));
    write(x, withTiming(0, { duration: Motion.base }));
    write(y, withTiming(0, { duration: Motion.base }));
    write(saved, 1);
    write(savedX, 0);
    write(savedY, 0);
  };

  const pinch = Gesture.Pinch()
    .onUpdate((event) => {
      write(scale, clampZoom(saved.value * event.scale));
      // A pinch that shrinks also has to pull the picture back
      // towards centre, or the edge it was panned to comes into view
      // as the overflow disappears.
      write(x, clampPan(x.value, width, scale.value));
      write(y, clampPan(y.value, height, scale.value));
    })
    .onEnd(() => {
      // **The zoom is kept, so the picture can then be moved.**
      //
      // It was briefly transient - springing back the instant the
      // fingers lifted - because a zoomed picture and the page
      // behind it both want a vertical drag, and that was the
      // cheapest way to stop the page getting stuck. It also made
      // the whole thing useless for its actual purpose: looking at
      // the part of a photograph the shell cropped, which takes two
      // hands if the zoom only lasts as long as the pinch.
      //
      // So the zoom stays and the conflict is arbitrated instead:
      // while the picture is bigger than its frame the drag is
      // the picture's, and the page does not scroll. `reaction`
      // below is what keeps that honest.
      if (!isZoomed(scale.value)) {
        settle();
        return;
      }
      write(saved, scale.value);
      write(savedX, x.value);
      write(savedY, y.value);
    });

  const pan = Gesture.Pan()
    // Two fingers mid-pinch would otherwise read as a drag from
    // wherever their average happens to be, which makes the picture
    // jump at the start of every pinch.
    .averageTouches(true)
    // **Off entirely until there is something to move.** One finger
    // is enough once zoomed - dragging a photograph around should
    // not need two hands - and that is only safe because the
    // gesture does not exist at the fit, where the same one-finger
    // drag is how the page scrolls.
    .enabled(zoomed)
    .onStart(() => {
      write(savedX, x.value);
      write(savedY, y.value);
    })
    .onUpdate((event) => {
      write(x, clampPan(savedX.value + event.translationX, width, scale.value));
      write(y, clampPan(savedY.value + event.translationY, height, scale.value));
    });

  const doubleTap = Gesture.Tap()
    .numberOfTaps(2)
    // Off at the fit too. A double-tap gesture in front of a
    // single-tap target makes every single tap wait to find out
    // whether a second one is coming, and the tap on this picture
    // opens it full screen. It is only the way *out* of a zoom, so
    // it need not exist until there is one.
    .enabled(zoomed)
    // The way out, and the reason keeping the zoom is safe. Pinching
    // back down on a picture that fills the screen is fiddly, and
    // without this somebody could be left on a page that will not
    // scroll with no obvious way to release it.
    .onEnd(() => {
      if (isZoomed(scale.value)) settle();
    });

  /**
   * The scroll lock, driven by the scale itself.
   *
   * **Not by the gesture, which is what broke it.** The first
   * version announced a pinch on `onStart` and the end of one on
   * `onEnd` - but `onEnd` only released the lock when the pinch
   * happened to finish at the fit, so anybody who zoomed in and let
   * go was left on a page that would not scroll, for good.
   *
   * Watching the value cannot drift from it: the lock is on exactly
   * while the picture is larger than its frame, however it got
   * there and however it comes back.
   */
  useAnimatedReaction(
    () => isZoomed(scale.value),
    (zoomed, was) => {
      if (zoomed !== was) runOnJS(tell)(zoomed);
    },
  );

  // Leaving while zoomed would hand the next screen a scaled
  // picture, and tell nobody that the pinch had ended.
  useEffect(
    () => () => {
      onZoomedChange?.(false);
    },
    [onZoomedChange],
  );

  const moved = useAnimatedStyle(() => ({
    transform: [
      { translateX: x.value },
      { translateY: y.value },
      { scale: scale.value },
    ],
  }));

  return (
    <GestureDetector
      gesture={Gesture.Simultaneous(Gesture.Exclusive(doubleTap, pan), pinch)}>
      <Animated.View style={[style, moved]}>{children}</Animated.View>
    </GestureDetector>
  );
}
