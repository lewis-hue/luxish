import {
  createContext,
  use,
  useCallback,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';

import {
  AT_REST,
  type Scrolling,
  immersed,
  scrolled,
} from '@/features/navigation/attention';

/**
 * Whether the screen currently wants the bottom edge to itself.
 *
 * **A channel, because the two halves are far apart.** The tab bar
 * is mounted once at the root so it can float over every screen; the
 * thing that knows whether somebody is looking at a photograph or
 * browsing past it is the scroll view inside the screen. Neither can
 * see the other, so the posture travels through here.
 *
 * It holds a boolean rather than the scroll offset on purpose. An
 * offset changes on every frame of every scroll and would re-render
 * the whole tree under the provider sixty times a second; the
 * posture changes a handful of times in a session.
 */
const Attention = createContext<{
  immersed: boolean;
  setImmersed: (value: boolean) => void;
  /** True while a downward scroll has sent the bar away. */
  stoodDown: boolean;
  setStoodDown: (value: boolean) => void;
}>({
  immersed: false,
  setImmersed: () => undefined,
  stoodDown: false,
  setStoodDown: () => undefined,
});

export function AttentionProvider({ children }: { children: ReactNode }) {
  const [isImmersed, setImmersed] = useState(false);
  const [stoodDown, setStoodDown] = useState(false);
  const value = useMemo(
    () => ({ immersed: isImmersed, setImmersed, stoodDown, setStoodDown }),
    [isImmersed, stoodDown],
  );
  return <Attention value={value}>{children}</Attention>;
}

/**
 * Report which way a list is being scrolled.
 *
 * Separate from `useImmersion`, which answers "is this a looking page
 * or a browsing page". This answers "which way are they going", and
 * any scrolling screen can report it - a board, a thread, a grid.
 *
 * **Reset on the way out**, for the same reason immersion resets: a
 * screen that leaves while the bar is down would take the bar with
 * it, and the next screen may never scroll.
 */
export function useScrollDirection() {
  const { stoodDown, setStoodDown } = use(Attention);
  const state = useRef<Scrolling>(AT_REST);

  const onScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const next = scrolled(state.current, event.nativeEvent.contentOffset.y);
      state.current = next;
      // Only on a change: this runs on every frame, and a setState
      // with the same value is cheap but not free sixty times a
      // second.
      if (next.hidden !== stoodDown) setStoodDown(next.hidden);
    },
    [stoodDown, setStoodDown],
  );

  const show = useCallback(() => {
    state.current = AT_REST;
    setStoodDown(false);
  }, [setStoodDown]);

  return { onScroll, show };
}

/** What the tab bar reads. */
export function useAttention() {
  return use(Attention);
}

/**
 * Report scroll posture from a screen that opens on one thing.
 *
 * Returns the handler to put on the scroll view and the setter for
 * the hero's measured height. Hand both to the screen and it will
 * keep the bar out of the way while the picture is what somebody is
 * looking at.
 *
 * **Reset on the way out.** A screen that leaves while immersed
 * would otherwise take the bar with it: the next screen is a list,
 * nothing on it ever reports a posture, and the bar would stay
 * hidden until something happened to set it back.
 */
export function useImmersion() {
  const { immersed: isImmersed, setImmersed } = useAttention();
  /** The hero's measured height, which the threshold is a fraction of. */
  const focusHeight = useRef(0);

  // The posture is read from state rather than mirrored into a ref.
  // Mirroring would mean writing a ref during render, and the
  // handler is rebuilt only when the posture actually flips - twice
  // in the life of a pin, not once per frame.
  const onScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const next = immersed({
        offsetY: event.nativeEvent.contentOffset.y,
        focusHeight: focusHeight.current,
        was: isImmersed,
      });
      // Only on a change. `setState` with the same value is cheap but
      // this runs on every scroll frame, and cheap sixty times a
      // second is not free.
      if (next !== isImmersed) setImmersed(next);
    },
    [isImmersed, setImmersed],
  );

  const measureFocus = useCallback(
    (height: number) => {
      if (height > 0 && height !== focusHeight.current) {
        focusHeight.current = height;
      }
    },
    [],
  );

  const release = useCallback(() => setImmersed(false), [setImmersed]);

  return { onScroll, measureFocus, release };
}
