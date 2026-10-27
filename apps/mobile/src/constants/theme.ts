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
    /**
     * The visible boundary of a control: input wells, outlined buttons.
     *
     * Separate from `border` because `border` is 1.32:1 against the page, which
     * is fine for a divider and fails WCAG 1.4.11's 3:1 for anything that
     * bounds a control. Same hue family, so the warmth survives.
     */
    borderStrong: '#9A8C7E',

    /* Semantic states. Warm on purpose: olive and ochre sit in the same half of
       the wheel as the burgundy accent, where a stock #00C853 green or #2196F3
       blue would be the one cold thing on the screen and would read instantly
       as a component library someone dropped in. There is no `info` token for
       exactly that reason; informational text uses `textSecondary`. */
    /** Confirmed, saved, available. */
    success: '#51732B',
    /** Needs attention but nothing is lost: in the wash, low confidence. */
    warning: '#866327',
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
    borderStrong: '#6B6157',
    /** Burgundy lifted for dark ground; `accentText` inverts to stay legible. */
    accent: '#D98A9E',
    accentText: '#2B0D18',
    success: '#698F3D',
    warning: '#AB7C2B',
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

/**
 * The smallest type the app is allowed to render.
 *
 * iOS's smallest built-in text style, Caption 2, is 11pt. Anything under that
 * is below the platform's own legibility floor, which is why it exists as a
 * constant rather than a habit: a test asserts no style goes under it.
 */
export const MinFontSize = 11;

/**
 * Named text sizes, so a screen never picks a number.
 *
 * Mapped onto the iOS scale where there is an equivalent, because matching the
 * platform is what makes text feel native at every Dynamic Type setting.
 */
export const FontSize = {
  /** iOS Caption 2. The floor. Used for image badges and meta labels. */
  meta: 11,
  /** iOS Caption 1. */
  caption: 12,
  /** iOS Footnote. */
  footnote: 13,
  /** iOS Subhead. */
  subhead: 15,
  /** iOS Body / Headline. */
  body: 17,
  /** iOS Title 3. */
  title3: 20,
  /** iOS Title 2. */
  title2: 22,
  /** iOS Title 1. */
  title1: 28,
  /** iOS Large Title. */
  largeTitle: 34,
} as const;

/**
 * Tracking for uppercase labels.
 *
 * Caps set at default tracking read as cramped; the premium editorial
 * convention is wide positive tracking on small caps labels.
 */
export const Tracking = {
  label: 1.2,
  wide: 1.4,
} as const;

/**
 * The smallest touchable area, per Apple's 44pt and Material's 48dp.
 *
 * Applied as `minHeight`/`minWidth` or via `hitSlop` on anything smaller than
 * this visually.
 */
export const TapTarget = 44;

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
 * Aspect ratios for image cells.
 *
 * `garment` is 3:4 rather than square, for a specific reason: a phone camera
 * shoots 3:4 portrait by default, and wardrobe photos are taken on a phone. A
 * cell that matches the camera means the common case needs no crop at all.
 * A square cell, by contrast, cuts a coat or a dress around the knee, and the
 * wardrobe is the user's own clothes, where a wrong crop reads as a bug.
 *
 * 3:4 is also where the market has settled for phone-shot fashion: Poshmark
 * moved its grid from 1:1 to 3:4 in March 2026 and said why, that sellers'
 * cameras already default to portrait. Professional product shots go taller
 * (SSENSE pads everything to 2:3), but we are not shooting studio product.
 *
 * The matching rule is **pad, never crop**: `contentFit: 'contain'` over a
 * warm neutral. SSENSE's pipeline uses letterbox padding on every product
 * image and cropping on none of them.
 */
export const AspectRatio = {
  /** Editorial and inspiration cards. */
  editorial: 3 / 4,
  /** Wardrobe cells and garment thumbnails. Pad to fit; never crop. */
  garment: 3 / 4,
  /** Short-form community video. */
  reel: 9 / 16,
} as const;

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
