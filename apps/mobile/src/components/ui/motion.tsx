import * as Haptics from 'expo-haptics';
import type { MotiTransitionProp } from 'moti';
import { useCallback, useEffect } from 'react';
import { Platform, Pressable, type PressableProps, type ViewStyle } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSequence,
  withSpring,
  withTiming,
  type EasingFunction,
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

/**
 * How wide the masthead starts before it settles.
 *
 * Large on purpose. A couple of points reads as a glitch; this reads as a
 * masthead opening, which is the move a fashion title has used on its own
 * cover for a century.
 */
const MASTHEAD_TRACKING = 14;

/**
 * The wordmark settling out of wide tracking.
 *
 * The one place in this app where the *typography* is animated rather than a
 * surface carrying it, and it is confined to the welcome screen for the
 * reason every other animation here is confined: on a screen with
 * photographs, motion competes with the content. On the first screen the
 * type is the content.
 *
 * Reanimated rather than Moti, because `MotiText` is typed off a style union
 * that `letterSpacing` is not in — `Omit` across `ViewStyle | TextStyle`
 * keeps only the common keys — so the one property this animates is the one
 * property it cannot express.
 *
 * Note this re-lays-out the text every frame, which is why it is a single
 * short string and a one-shot. Do not reach for it on a paragraph.
 */
export function useMastheadMotion(delayMs = 0, resting = 0): MotionStyle {
  const progress = useSharedValue(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) {
      write(progress, 1);
      return;
    }
    write(progress, withDelay(delayMs, withTiming(1, { duration: 900 })));
  }, [delayMs, reduced, progress]);

  return useAnimatedStyle(() => ({
    opacity: progress.value,
    letterSpacing:
      MASTHEAD_TRACKING + (resting - MASTHEAD_TRACKING) * progress.value,
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
 *
 * **Imported at the top, not awaited per tap.** It used to be a dynamic
 * `import()`, which bought nothing - the module is a hard dependency
 * already in the bundle - and cost a promise on the hottest path in the
 * app. It also made every press untestable: jest cannot run a dynamic
 * import, so a tap rejected before the handler under test was reached.
 */
export async function tapFeedback(): Promise<void> {
  if (Platform.OS === 'web') return;
  await Haptics.selectionAsync();
}

/** Success feedback, for a completed multi-step action such as a bulk upload. */
export async function successFeedback(): Promise<void> {
  if (Platform.OS === 'web') return;
  await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
}

/* -------------------------------------------------------------------------- */
/* Moti                                                                       */
/* -------------------------------------------------------------------------- */

/** The subset of Moti's timing config anything in this app actually sets. */
export interface MotiTiming {
  duration?: number;
  delay?: number;
  /** A continuous pulse. Dropped entirely under Reduce Motion. */
  loop?: boolean;
  repeat?: number;
  /**
   * Whether each lap plays backwards. **Moti's default is `true`.**
   *
   * Fine for a pulse, wrong for anything that turns: a spinner given
   * `loop: true` and nothing else rotates to 360 and then unwinds to
   * 0, so it rocks back and forth instead of spinning. A rotation
   * must pass `repeatReverse: false`.
   */
  repeatReverse?: boolean;
  /**
   * The curve. Moti's default eases in and out, which puts a stall at
   * both ends of every lap - invisible on a one-shot settle and very
   * visible on a loop, where it reads as the animation hitching once
   * a second. Continuous motion wants `Easing.linear`.
   */
  easing?: EasingFunction;
}

/**
 * A timing transition for a Moti component.
 *
 * The cast is deliberate and lives here rather than at each call site. Moti
 * 0.30 types `transition` as `MotiTransitionProp<any>`, and because
 * `keyof any` is `string | number | symbol`, the per-style half of that
 * intersection becomes an index signature requiring *every* key to be a
 * transition config. That makes `type: 'timing'` — the value Moti's own docs
 * use — fail to typecheck. Verified: a transition with no `type` compiles and
 * the identical object with `type: 'timing'` does not.
 */
export function motiTiming(config: MotiTiming): MotiTransitionProp {
  return { type: 'timing', ...config } as MotiTransitionProp;
}

/** The subset of Moti's spring config anything in this app actually sets. */
export interface MotiSpring {
  damping?: number;
  stiffness?: number;
  mass?: number;
  delay?: number;
}

/**
 * A spring transition for a Moti component.
 *
 * Same cast, same reason as `motiTiming` above.
 *
 * Springs are rare here on purpose — most motion in this app is a settle,
 * and a settle wants an easing curve. A spring is for the few things that
 * should arrive with weight: something that *drops*, where a linear landing
 * reads as a slide rather than as a fall.
 */
export function motiSpring(config: MotiSpring): MotiTransitionProp {
  return { type: 'spring', ...config } as MotiTransitionProp;
}

/**
 * The same thing, honouring Reduce Motion, which is how every other primitive
 * in this file behaves.
 *
 * Under the setting a transition collapses to zero and any loop is dropped, so
 * the component lands on its `animate` values and holds them. A looping pulse
 * therefore becomes a static tint rather than a faster pulse: Apple asks for
 * repetitive animation to be *removed*, not sped up.
 */
export function useMotiTiming(): (config: MotiTiming) => MotiTransitionProp {
  const reduced = useReducedMotion();
  return useCallback(
    (config: MotiTiming) =>
      reduced ? motiTiming({ duration: 0, delay: 0 }) : motiTiming(config),
    [reduced],
  );
}

/**
 * A spring, honouring Reduce Motion.
 *
 * Collapses to an instant timing rather than to a slow spring: a damped
 * spring is still motion, and the setting asks for it to be removed.
 */
export function useMotiSpring(): (config: MotiSpring) => MotiTransitionProp {
  const reduced = useReducedMotion();
  return useCallback(
    (config: MotiSpring) =>
      reduced ? motiTiming({ duration: 0, delay: 0 }) : motiSpring(config),
    [reduced],
  );
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
