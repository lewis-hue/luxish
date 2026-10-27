/**
 * The app's single token source of truth.
 *
 * Extends the create-expo-app token file in its own idiom rather than introducing a
 * second system beside it: `Colors` keeps its `light`/`dark` shape and its existing
 * key names, `Spacing` keeps its ordinal names, `Fonts` keeps its `Platform.select`
 * form. `Radius` and `Motion` are new because the template had no equivalent.
 *
 * Visual direction (§3): editorial fashion — warm neutral paper surfaces, warm
 * charcoal text, a single burgundy accent, restrained motion. Photography carries the
 * colour; the chrome stays quiet.
 *
 * These are explicit light/dark pairs rather than platform semantic colours because
 * the brief specifies a particular warm-neutral surface and burgundy accent that no
 * platform palette provides. Every pair below is contrast-checked in
 * `__tests__/theme.test.ts` — do not edit a value without re-running that test.
 */

import '@/global.css';

import { Platform } from 'react-native';

export const Colors = {
  light: {
    /** Warm paper, not pure white — pure white makes garment photography look cold. */
    background: '#FAF7F2',
    /** Raised surface: cards, sheets, input wells. */
    backgroundElement: '#F2EDE5',
    backgroundSelected: '#E8E0D4',
    /** Warm charcoal rather than #000 — softer against a warm ground. */
    text: '#1F1B1A',
    textSecondary: '#6B625C',
    /** Hairlines and dividers. Never used for text. */
    border: '#E0D8CC',
    /** The one accent. Used for primary actions and active states, never decoration. */
    accent: '#7A1F3D',
    /** Text and icons placed on top of `accent`. */
    accentText: '#FFFFFF',
    /** Destructive actions and error states. */
    danger: '#9B2226',
    /** Scrim behind sheets and image viewers. */
    scrim: 'rgba(31, 27, 26, 0.55)',
  },
  dark: {
    background: '#121010',
    backgroundElement: '#1E1A19',
    backgroundSelected: '#2A2524',
    text: '#F5F0EA',
    textSecondary: '#A79E96',
    border: '#332D2B',
    /** Burgundy lifted for dark ground; `accentText` inverts to stay legible. */
    accent: '#D98A9E',
    accentText: '#2B0D18',
    danger: '#F08A82',
    scrim: 'rgba(0, 0, 0, 0.65)',
  },
} as const;

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;

/**
 * The display face, loaded at startup by the root layout.
 *
 * Bodoni Moda is a high-contrast didone — the register fashion magazines have used
 * for a century, and specific enough that the app does not read as a template. It is
 * used for headings and nothing else: body copy and controls stay on the system face,
 * because a custom UI font is the fastest way to make a native app feel like a
 * website wearing a costume.
 */
export const Display = {
  regular: 'BodoniModa_400Regular',
  semibold: 'BodoniModa_600SemiBold',
} as const;

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` — editorial headings. */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: 'var(--font-display)',
    serif: 'var(--font-serif)',
    rounded: 'var(--font-rounded)',
    mono: 'var(--font-mono)',
  },
});

/** 4-point grid. Template names kept; `three` (16) is the screen edge padding. */
export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

/** Pair every non-capsule radius with `borderCurve: 'continuous'`. */
export const Radius = {
  sm: 8,
  md: 12,
  lg: 16,
  /** Capsules: chips, filter pills, avatar rings. */
  full: 9999,
} as const;

/**
 * Durations in ms. Restrained by direction — nothing announces itself.
 * Honour `useReducedMotion()` before animating; see `hooks/use-theme.ts`.
 */
export const Motion = {
  /** Press and toggle feedback. */
  fast: 140,
  /** Element enter/exit. */
  base: 220,
  /** Sheets and screen-level surfaces. */
  slow: 360,
} as const;

/**
 * Consistent aspect ratios keep style tiles and wardrobe grids visually aligned (§3).
 * Editorial portrait for inspiration, square for wardrobe items.
 */
export const AspectRatio = {
  /** Style tiles and inspiration cards. */
  editorial: 3 / 4,
  /** Wardrobe grid cells and garment thumbnails. */
  garment: 1,
  /** Short-form community video. */
  reel: 9 / 16,
} as const;

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
