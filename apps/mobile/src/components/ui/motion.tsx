import { useCallback, useEffect } from 'react';
import { Platform, Pressable, type PressableProps, type ViewStyle } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSequence,
  withSpring,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';

import { Motion, Spacing } from '@/constants/theme';
import { useReducedMotion } from '@/hooks/use-theme';

/**
 * Shared motion primitives.
 *
 * The direction is restrained: nothing announces itself. Motion here does one
 * of three jobs and nothing else.
 *
 * 1. **Confirm a touch.** A press is a physical act and wants a physical
 *    answer, so tiles compress slightly rather than fading. Fading a
 *    photograph reads as "loading", not "pressed".
 * 2. **Explain where content came from.** A grid that rises into place reads
 *    as arriving; the same grid appearing instantly reads as a redraw.
 * 3. **Mark a state the user caused.** The favourite pop exists because a
 *    heart that silently changes colour is easy to miss, and missing it means
 *    tapping twice.
 *
 * Anything that cannot be justified by one of those is decoration, and
 * decoration in a fashion app competes with the photographs, which are the
 * actual content.
 *
 * **Every primitive collapses to zero under Reduce Motion**, which Apple's own
 * guidance asks for: when the setting is on, "reduce automatic and repetitive
 * animations, including zooming, scaling, and peripheral motion". These return
 * a static style rather than a faster animation, because a shorter version of
 * an unwanted animation is still unwanted.
 */

/** A `Pressable` that can take an animated style. */
export const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

/**
 * Assign to a Reanimated shared value.
 *
 * Not indirection for its own sake. React's `react-hooks/immutability` rule
 * treats `.value` as React-owned state and rejects an assignment written
 * inside a hook's returned closure, where it cannot tell the closure only ever
 * runs from an event. A Reanimated shared value is mutable by design, and
 * driving it from a handler is the documented pattern. Routing the assignment
 * through a plain function satisfies the rule honestly, with no suppression
 * anywhere in this file.
 */
function write<T>(shared: SharedValue<T>, next: T): void {
  shared.value = next;
}

/* -------------------------------------------------------------------------- */
/* Press                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * How far a pressed surface compresses.
 *
 * Deliberately small. At 0.95 the movement is a bounce and draws the eye; at
 * 0.975 it reads as the surface taking the weight of the finger, which is the
 * intent.
 */
export const PRESS_SCALE = 0.975;

/** Firm and quick: a touch response that overshoots feels like a toy. */
const PRESS_SPRING = { damping: 20, stiffness: 400 } as const;

/** What `useAnimatedStyle` returns, named so callers can hold it. */
type MotionStyle = ReturnType<typeof useAnimatedStyle<ViewStyle>>;

export interface PressMotion {
  style: MotionStyle;
  onPressIn: () => void;
  onPressOut: () => void;
}

/**
 * Scale-on-press, as a spread-able set of props.
 *
 * Returns handlers rather than wrapping a component, so a caller keeps its own
 * `Pressable` and whatever accessibility props it already sets. Spread
 * `onPressIn`/`onPressOut` and put `style` in the style array.
 */
export function usePressMotion(scale = PRESS_SCALE): PressMotion {
  const pressed = useSharedValue(0);
  const reduced = useReducedMotion();

  const style = useAnimatedStyle(() => ({
    transform: [{ scale: reduced ? 1 : 1 - pressed.value * (1 - scale) }],
  }));

  const onPressIn = useCallback(() => {
    write(pressed, withSpring(1, PRESS_SPRING));
  }, [pressed]);

  const onPressOut = useCallback(() => {
    write(pressed, withSpring(0, PRESS_SPRING));
  }, [pressed]);

  return { style, onPressIn, onPressOut };
}

/* -------------------------------------------------------------------------- */
/* Entrance                                                                   */
/* -------------------------------------------------------------------------- */

/** Gap between consecutive cells. */
export const STAGGER_STEP_MS = 40;

/**
 * Cells after this many stop waiting their turn.
 *
 * Without a cap, cell 30 in a long grid would wait 1.2 seconds, so the list
 * would appear to load slowly when in fact it had already loaded. The cap
 * keeps the effect on the first screenful, which is the only part a stagger
 * can be perceived in anyway.
 */
export const STAGGER_MAX_INDEX = 8;

/** How far a cell travels. Small enough to read as settling, not flying in. */
const RISE_DISTANCE = Spacing.two;

/**
 * Fade-and-rise for a grid cell, staggered by position.
 *
 * Pass the cell's index. Returns a style to put in the cell's style array.
 */
export function useEntranceMotion(index = 0): MotionStyle {
  const progress = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) {
      // Jump straight to the resting state. Not an animation with duration 0,
      // which would still schedule a frame.
      write(progress, 1);
      return;
    }
    const delay = Math.min(index, STAGGER_MAX_INDEX) * STAGGER_STEP_MS;
    write(progress, withDelay(delay, withTiming(1, { duration: Motion.base })));
  }, [index, reduced, progress]);

  return useAnimatedStyle(() => ({
    opacity: progress.value,
    transform: [{ translateY: (1 - progress.value) * RISE_DISTANCE }],
  }));
}

/* -------------------------------------------------------------------------- */
/* State change                                                               */
/* -------------------------------------------------------------------------- */

/** The one place a slight overshoot is wanted, so the change is noticed. */
const POP_SPRING = { damping: 9, stiffness: 320 } as const;

/**
 * A brief pop, for a state the user just caused.
 *
 * Used on the favourite heart. Returns a style plus a `pop()` to call from the
 * handler. Deliberately not driven off the boolean state: the animation marks
 * *the act*, so it should not replay when the same value arrives from
 * elsewhere, such as a sync.
 */
export function usePopMotion(): { style: MotionStyle; pop: () => void } {
  const scale = useSharedValue(1);
  const reduced = useReducedMotion();

  const style = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  const pop = useCallback(() => {
    if (reduced) return;
    write(
      scale,
      withSequence(
        withTiming(1.22, { duration: Motion.fast }),
        withSpring(1, POP_SPRING),
      ),
    );
  }, [reduced, scale]);

  return { style, pop };
}

/* -------------------------------------------------------------------------- */
/* Haptics                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Selection feedback, guarded for web.
 *
 * The lightest tap the platform offers. Anything heavier on a browse grid
 * becomes noise within a few scrolls, which is why there is one helper rather
 * than a choice at each call site.
 */
export async function tapFeedback(): Promise<void> {
  if (Platform.OS === 'web') return;
  const Haptics = await import('expo-haptics');
  await Haptics.selectionAsync();
}

/** Success feedback, for a completed multi-step action such as a bulk upload. */
export async function successFeedback(): Promise<void> {
  if (Platform.OS === 'web') return;
  const Haptics = await import('expo-haptics');
  await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
}

/* -------------------------------------------------------------------------- */
/* Convenience wrapper                                                        */
/* -------------------------------------------------------------------------- */

export interface MotionPressableProps extends PressableProps {
  /** Grid position, for the entrance stagger. Omit for a lone control. */
  index?: number;
  /** Set false for a control that should not move under the finger. */
  animatePress?: boolean;
  /** Set false inside an already-animating parent. */
  animateEntrance?: boolean;
  scale?: number;
  haptic?: boolean;
  style?: PressableProps['style'];
  children?: React.ReactNode;
}

/**
 * A `Pressable` with the house press and entrance motion already attached.
 *
 * For the common case. Reach for the hooks directly when a component needs to
 * drive the same values from something else.
 */
export function MotionPressable({
  index,
  animatePress = true,
  animateEntrance = true,
  scale,
  haptic = true,
  onPressIn,
  onPressOut,
  style,
  children,
  ...rest
}: MotionPressableProps) {
  const press = usePressMotion(scale);
  const entrance = useEntranceMotion(index);

  return (
    <AnimatedPressable
      {...rest}
      onPressIn={(event) => {
        if (animatePress) press.onPressIn();
        if (haptic) void tapFeedback();
        onPressIn?.(event);
      }}
      onPressOut={(event) => {
        if (animatePress) press.onPressOut();
        onPressOut?.(event);
      }}
      style={[
        animatePress ? press.style : undefined,
        animateEntrance ? entrance : undefined,
        style as never,
      ]}>
      {children}
    </AnimatedPressable>
  );
}
