import { BlurView } from 'expo-blur';
import {
  router,
  usePathname,
  useRootNavigationState,
} from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useEffect, useState } from 'react';
import { Keyboard, Platform, Pressable, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Colors, Radius, Spacing, TapTarget } from '@/constants/theme';
import { useAttention } from '@/features/navigation/attention-context';
import { useReducedMotion, useScheme } from '@/hooks/use-theme';

/**
 * The five primary destinations, as a bar that floats over everything.
 *
 * **It lives at the root, not in the tab group.** It used to be drawn
 * inside `(tabs)/_layout`, which meant any pushed screen - a pin, the
 * closet, the stylist - covered it, and getting to another tab was a
 * back gesture first. Rendered above the whole stack it is always
 * there, which is what makes a board you can dive into and out of
 * feel like one surface rather than a pile of screens.
 *
 * **It floats because the content underneath is photographs.** A bar
 * docked to the bottom edge draws a hard line across a staggered
 * board and ends it early; chips sitting on top let the pictures run
 * to the bottom of the screen. Every screen pads its scroll by
 * `BottomTabInset`, so nothing is trapped underneath.
 *
 * **Icons only.** Five labels do not fit on one line of a floating
 * bar at any readable size, and these are the icons the platform
 * already uses for these ideas. Each chip carries its name as its
 * accessibility label, so nothing is lost to a screen reader.
 */
export const DESTINATIONS = [
  {
    name: 'index',
    href: '/',
    label: 'Discover',
    icon: { ios: 'square.grid.2x2.fill', android: 'grid_view', web: 'grid_view' },
  },
  {
    name: 'search',
    href: '/search',
    label: 'Search',
    icon: { ios: 'magnifyingglass', android: 'search', web: 'search' },
  },
  {
    name: 'wardrobe',
    href: '/wardrobe',
    label: 'Wardrobe',
    icon: { ios: 'hanger', android: 'apparel', web: 'apparel' },
  },
  {
    name: 'studio',
    href: '/studio',
    label: 'Studio',
    icon: { ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' },
  },
  {
    name: 'profile',
    href: '/profile',
    label: 'Profile',
    icon: {
      ios: 'person.crop.circle.fill',
      android: 'account_circle',
      web: 'account_circle',
    },
  },
] as const satisfies readonly {
  name: string;
  href: string;
  label: string;
  icon: SymbolViewProps['name'];
}[];

/**
 * Screens that draw their own bottom controls.
 *
 * Two bars at the bottom of one screen is two places to look for the
 * way out, and on an editor the floating one would sit over the
 * controls somebody is using. These are the only screens that own
 * that space; everywhere else keeps the bar.
 */
const OWNS_THE_BOTTOM: readonly string[] = [
  '/compose',
  '/collage',
  '/sign-in',
  '/welcome',
  // A message thread is a composer pinned to the bottom edge with
  // quick replies above it. The bar landed squarely on both.
  '/messages',
];

/**
 * Web draws its own, so this one stays off it.
 *
 * `(tabs)/_layout.web.tsx` lays the destinations out as a horizontal
 * bar across the top, which is what a browser window wants and not an
 * imitation of a phone. Rendering this over it would be two navs.
 */
const ON_WEB = process.env.EXPO_OS === 'web';

/**
 * Whether the bar belongs on this path.
 *
 * Exported because it is the rule, and a bar appearing over an
 * editor's own controls is the kind of thing nobody notices until it
 * ships.
 */
export function showsTabBar(pathname: string): boolean {
  if (ON_WEB) return false;
  return !OWNS_THE_BOTTOM.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
}

/**
 * Whether the bar belongs on screen at all, right now.
 *
 * **The keyboard is the general case; the list above is the
 * exception.** A deny-list only knows the screens somebody
 * remembered to add, and every screen with a text field is a screen
 * where the bar can land on what is being typed into. Whenever the
 * keyboard is up there is something more important at the bottom of
 * the screen than five navigation chips, so the bar stands down -
 * on every screen, including ones written after this.
 *
 * The list stays for the screens that own their bottom edge with the
 * keyboard *down*: a message thread's composer, the collage
 * editor's controls.
 */
export function tabBarShowing(input: {
  pathname: string;
  keyboardUp: boolean;
  /**
   * Whether the screen is currently asking for the bottom edge.
   *
   * Reported by the screen from its scroll position rather than
   * derived from the route, because one route is both things in
   * turn - see `features/navigation/attention`.
   */
  immersed?: boolean;
}): boolean {
  if (!showsTabBar(input.pathname)) return false;

  // **A tab root keeps its bar whatever else is happening.**
  //
  // The two rules below are about getting out of the way, and on a
  // pushed screen that is safe: there is a back gesture and a
  // chevron, so the way out survives. On a tab root the bar *is*
  // the way out, and hiding it leaves somebody on a page with no
  // navigation at all.
  //
  // That was not theoretical. The stylist moved onto the wardrobe
  // page, which made a tab root contain a text field; tapping it
  // raised the keyboard, the keyboard rule removed the bar, and
  // the wardrobe has no chevron because tabs do not. The only way
  // on was to guess that dismissing the keyboard would bring the
  // navigation back.
  if (selectedHref(input.pathname)) return true;

  if (input.keyboardUp) return false;
  if (input.immersed) return false;
  return true;
}

/**
 * Which chip this exact path is.
 *
 * Null on a pushed screen, which is not the same as nothing being
 * lit - see `FloatingTabBar`. A pin has no chip of its own; the tab
 * it was opened from still does.
 */
export function selectedHref(pathname: string): string | null {
  const found = DESTINATIONS.find((destination) => destination.href === pathname);
  return found?.href ?? null;
}

/**
 * The tab whose section you are in, read off the navigator.
 *
 * **A pushed screen sits over a tab rather than replacing it.** The
 * bar lit nothing on a pin, which reads as five identical chips and
 * no sense of where you are, on the screen people spend the most
 * time on. The tab is the section you are in, not the one screen in
 * front of you.
 *
 * Taken from the tab navigator's own focused route rather than
 * remembered here, because the navigator is the thing that actually
 * knows: it keeps Discover focused underneath while a pin is pushed
 * over it. Two copies of that fact would be one to get out of step,
 * and this one needs no state and no effect to stay right.
 *
 * Defensive throughout: this walks a navigation tree whose shape is
 * the router's business, so anything unexpected falls back to
 * matching the path, which is always at least correct on a tab.
 */
export function tabFromState(state: unknown): string | null {
  const seen = new Set<unknown>();

  const walk = (node: unknown): string | null => {
    if (!node || typeof node !== 'object' || seen.has(node)) return null;
    seen.add(node);
    const here = node as {
      routes?: unknown[];
      index?: number;
      name?: string;
      state?: unknown;
    };
    const routes = Array.isArray(here.routes) ? here.routes : null;

    if (routes) {
      // A tab navigator's focused child is the tab somebody is on.
      const focused = routes[here.index ?? 0] as
        | { name?: string; state?: unknown }
        | undefined;
      const match = DESTINATIONS.find(
        (destination) => destination.name === focused?.name,
      );
      if (match) return match.href;
      for (const route of routes) {
        const found = walk((route as { state?: unknown })?.state);
        if (found) return found;
      }
    }
    return walk(here.state);
  };

  return walk(state);
}

/**
 * Pushed screens that belong to one tab wherever they were opened from.
 *
 * **A pin is a Discover thing.** Normally the navigator is right
 * about which section a pushed screen sits in - it was pushed over
 * some tab, and that tab is where going back leads. A fit is the
 * exception: it is the same page whether it was reached from the
 * board, a search result, a notification or the author's own
 * profile, and lighting a different chip each time makes the bar
 * report the route taken rather than where somebody is. Opening your
 * own upload lit Profile, which said the pin was a profile page.
 *
 * Keyed by first segment, so `/fit/<anything>` is one entry.
 */
const BELONGS_TO: Record<string, string> = {
  // A pin is a Discover thing.
  fit: '/',
  // Your account and everything under it is a Profile thing.
  //
  // These are only reachable from your own account area, so the
  // navigator is usually right about them - but only usually: it
  // reports whichever tab happened to be focused underneath, and
  // these screens are pushed onto the root stack rather than into
  // the profile tab's. Opening settings lit Discover.
  settings: '/profile',
  'notification-settings': '/profile',
  'profile-edit': '/profile',
  subscription: '/profile',
  insights: '/profile',
  saved: '/profile',
};

export function currentHref(
  pathname: string,
  fromNavigator: string | null,
): string | null {
  // A tab named outright wins: it is where somebody is, full stop.
  const named = selectedHref(pathname);
  if (named) return named;

  // Then a screen that belongs to one section wherever it came from.
  const [, head] = pathname.split('/');
  const owned = head ? BELONGS_TO[head] : undefined;
  if (owned) return owned;

  // Otherwise the navigator knows which tab this was pushed over.
  return fromNavigator;
}

/**
 * The drop, the wait, and the rise, in milliseconds.
 *
 * **Timed to finish with the screen, not after it.** `usePathname`
 * changes when the navigation commits rather than when its animation
 * ends, so some wait is needed or the bar rises through a screen
 * still arriving. But the first version waited `Motion.base` between
 * a `Motion.fast` drop and a `Motion.base` rise - 580ms in all, which
 * left the bar still moving for a third of a second after a pin had
 * landed, and the whole transition was reported as slow.
 *
 * A pin now cross-fades in 120ms and its hero spring settles about
 * 165ms after that. These add to roughly the same, so the bar is back
 * in place as the picture stops moving rather than trailing it.
 */
const DROP_MS = 90;
const SETTLE = 30;
const RISE_MS = 160;

export function FloatingTabBar() {
  const insets = useSafeAreaInsets();
  const pathname = usePathname();
  const reduced = useReducedMotion();

  // Which tab is focused underneath, straight from the navigator.
  const navigationState = useRootNavigationState();

  /**
   * Whether a keyboard is up anywhere.
   *
   * A boolean, not a tracked frame: this decides whether to render
   * at all, so it needs the fact rather than the geometry. The
   * house rule against `Keyboard.addListener` is about animating
   * against the keyboard's real frame, which this does not do.
   */
  const [keyboardUp, setKeyboardUp] = useState(false);

  useEffect(() => {
    const up = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      () => setKeyboardUp(true),
    );
    const down = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setKeyboardUp(false),
    );
    return () => {
      up.remove();
      down.remove();
    };
  }, []);

  const { immersed } = useAttention();

  /** 0 is up and in place, 1 is dropped clear of the bottom edge. */
  const down = useSharedValue(0);
  // How far down is far enough to be gone, shadow included.
  const drop = insets.bottom + Spacing.two + TapTarget + Spacing.five;

  useEffect(() => {
    // Down as the page leaves, up once the next one has arrived.
    //
    // The bar belongs to the app rather than to any one screen, so it
    // should not slide sideways with the content - but staying
    // perfectly still through a transition makes it look pasted on
    // top. Dropping out and coming back is the compromise: it is
    // clearly a separate surface, and it is clearly moving with you.
    if (reduced) {
      down.value = 0;
      return;
    }
    down.value = withSequence(
      withTiming(1, { duration: DROP_MS, easing: Easing.in(Easing.cubic) }),
      withDelay(
        SETTLE,
        withTiming(0, { duration: RISE_MS, easing: Easing.out(Easing.cubic) }),
      ),
    );
  }, [pathname, reduced, down]);

  const slide = useAnimatedStyle(() => ({
    transform: [{ translateY: down.value * drop }],
  }));

  // **Reading what somebody is doing, not only which screen is
  // open.** A fit's page opens as one photograph filling the screen
  // and the chips sat on it; scroll past the picture and the same
  // page is a grid of other fits, where the chips are how you
  // leave. The screen reports which of the two it currently is.
  if (!tabBarShowing({ pathname, keyboardUp, immersed })) return null;
  const selected = currentHref(pathname, tabFromState(navigationState));

  return (
    <Animated.View
      // `box-none` so the gaps between the chips pass taps through to
      // whatever is behind them. Without it the bar is an invisible
      // full-width strip that eats the bottom row of the board.
      pointerEvents="box-none"
      style={[
        {
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: insets.bottom + Spacing.two,
          flexDirection: 'row',
          justifyContent: 'center',
          gap: Spacing.two,
        },
        slide,
      ]}>
      {DESTINATIONS.map((destination) => (
        <TabChip
          key={destination.name}
          label={destination.label}
          icon={destination.icon}
          isFocused={selected === destination.href}
          onPress={() => {
            // `navigate` rather than `push`: from a pin, this returns
            // to the tab already in the stack instead of stacking a
            // second copy of it on top of the pin.
            router.navigate(destination.href);
          }}
        />
      ))}
    </Animated.View>
  );
}

/**
 * The selected chip's tint: `colors.accent`, carried at an alpha that still
 * reads as that colour.
 *
 * **It has to be the accent burgundy, not a wash of something near it.**
 * The accent is the app's one colour and it means "this is the live
 * thing"; a selected tab at 0.62 came out a dusty mauve that read as its
 * own colour rather than as the accent, which breaks the one association
 * the palette is carrying.
 *
 * Written as literals rather than derived from `colors.accent`, because
 * the two palettes need different alphas to land on the same reading.
 */
const SELECTED_WASH = {
  light: 'rgba(122, 31, 61, 0.92)',
  dark: 'rgba(217, 138, 158, 0.92)',
} as const;

function TabChip({
  label,
  icon,
  isFocused,
  onPress,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  isFocused: boolean;
  onPress: () => void;
}) {
  const scheme = useScheme();
  const colors = Colors[scheme];
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityLabel={label}
      accessibilityState={{ selected: isFocused }}
      onPress={onPress}
      style={({ pressed }) => ({
        // The selected chip is wider as well as tinted, so the bar reads
        // at a glance even before the colour registers.
        width: isFocused ? TapTarget + Spacing.five : TapTarget + Spacing.two,
        height: TapTarget + Spacing.one,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        // Clips the blur to the rounded shape; without it the pane is a
        // square behind a rounded border.
        overflow: 'hidden',
        borderWidth: 1,
        borderColor: isFocused ? colors.accent : colors.border,
        boxShadow: isFocused
          ? '0 6px 16px rgba(0, 0, 0, 0.18)'
          : '0 4px 12px rgba(0, 0, 0, 0.10)',
        opacity: pressed ? 0.7 : 1,
      })}>
      <BlurView
        intensity={isFocused ? 40 : 28}
        tint={scheme === 'dark' ? 'dark' : 'light'}
        style={{ position: 'absolute', width: '100%', height: '100%' }}
      />
      {isFocused ? (
        <View
          style={{
            position: 'absolute',
            width: '100%',
            height: '100%',
            backgroundColor: SELECTED_WASH[scheme],
          }}
        />
      ) : null}
      <SymbolView
        name={icon}
        size={isFocused ? 24 : 22}
        tintColor={isFocused ? colors.accentText : colors.textSecondary}
      />
    </Pressable>
  );
}
