/**
 * Resolved theme for the current appearance.
 *
 * Extends the template hook (which returned only colours) with the two things the
 * brief requires every animated or spaced surface to respect: the resolved scheme
 * name, and whether the user has asked for reduced motion (§3 accessibility).
 *
 * Learn more: https://docs.expo.dev/guides/color-schemes/
 */

import { AccessibilityInfo } from 'react-native';
import { useEffect, useState } from 'react';

// Platform-resolved: the .web variant guards against a hydration mismatch under
// server rendering. Importing from 'react-native' directly would bypass it.
import { useColorScheme } from '@/hooks/use-color-scheme';

import { Colors, Motion } from '@/constants/theme';

export type Scheme = 'light' | 'dark';

/** Colours only — kept as the default export shape the template components use. */
export function useTheme() {
  return Colors[useScheme()];
}

export function useScheme(): Scheme {
  return useColorScheme() === 'dark' ? 'dark' : 'light';
}

/**
 * True when the OS "Reduce Motion" setting is on. Subscribes to changes, because
 * the setting can be toggled while the app is foregrounded.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let active = true;
    AccessibilityInfo.isReduceMotionEnabled().then((value) => {
      if (active) setReduced(value);
    });
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduced);
    return () => {
      active = false;
      sub.remove();
    };
  }, []);

  return reduced;
}

/** Widened from the literal token type, because reduced motion returns zeros. */
export type Durations = { [K in keyof typeof Motion]: number };

/**
 * Durations that collapse to 0 when reduced motion is requested, so a caller can
 * pass them straight to an animation without branching at each call site.
 */
export function useMotion(): Durations {
  const reduced = useReducedMotion();
  if (!reduced) return Motion;
  return { fast: 0, base: 0, slow: 0 };
}

export function useThemeContext() {
  const scheme = useScheme();
  return {
    scheme,
    colors: Colors[scheme],
    motion: useMotion(),
    reducedMotion: useReducedMotion(),
  };
}
