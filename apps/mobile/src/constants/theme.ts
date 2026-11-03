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
    /**
     * White, and black on it.
     *
     * This was warm paper and warm charcoal, on the reasoning that
     * pure white makes garment photography look cold. The opposite
     * argument won: a tinted page sits next to every photograph on
     * the screen and tints all of them, and on a board that is
     * almost entirely photographs the page should be the one thing
     * with no opinion.
     */
    background: '#FFFFFF',
    /** Raised surface: cards, sheets, input wells. */
    backgroundElement: '#EFEFEF',
    backgroundSelected: '#E2E2E2',
    text: '#000000',
    textSecondary: '#5F5F5F',
    /** Hairlines and dividers. Never used for text. */
    border: '#E3E3E3',
    /** The one accent. Used for primary actions and active states, never decoration. */
    accent: '#7A1F3D',
    /** Text and icons placed on top of `accent`. */
    accentText: '#FFFFFF',
    /**
     * The visible boundary of a control: input wells, outlined buttons.
     *
     * Separate from `border`, which is a divider at 1.1:1 against the
     * page and fails WCAG 1.4.11's 3:1 for anything that bounds a
     * control.
     */
    borderStrong: '#767676',

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
    scrim: 'rgba(0, 0, 0, 0.55)',
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
 * One scheme's colours, widened from the literal hex types.
 *
 * `Colors.light` and `Colors.dark` infer as different literal types, so a
 * function taking one cannot be passed the other. This is the shape to accept
 * when a helper works with either.
 */
export type Palette = { readonly [K in ThemeColor]: string };

/** A state's meaning, independent of which colour currently carries it. */
export type Tone = 'success' | 'warning' | 'danger' | 'muted' | 'accent';

/**
 * Resolve a tone to a colour for the current scheme.
 *
 * Exists so no screen names a semantic colour directly. Features describe
 * *meaning* ("this garment is unavailable") and the palette decides what that
 * looks like, which is what lets the semantic colours be re-tuned in one place
 * without hunting through screens.
 *
 * `muted` maps to `textSecondary` rather than to a grey of its own: a state
 * the user chose, like archiving something, should read as ordinary rather
 * than as a warning about their own decision.
 */
export function toneColor(colors: Palette, tone: Tone): string {
  switch (tone) {
    case 'success':
      return colors.success;
    case 'warning':
      return colors.warning;
    case 'danger':
      return colors.danger;
    case 'accent':
      return colors.accent;
    case 'muted':
      return colors.textSecondary;
  }
}

/**
 * The two faces, loaded at startup by the root layout.
 *
 * **Archivo carries every heading, as of 2026-11-02.** Bodoni was the
 * display face for titles across the app, and the product owner's
 * call is that it did not read as one app: a screen opened with a
 * didone or with a grotesque depending on which screen it was, and
 * nothing predicted which. Headings are now Archivo at the heavy end
 * of its axis - one voice, closer to the reference the rest of the
 * board is built against.
 *
 * Bodoni survives in exactly one place: the wordmark on the welcome
 * screen. That is a logotype rather than page furniture, and a brand
 * mark is the one thing that should not match everything around it.
 *
 * **Bodoni Moda** was chosen to carry every heading: a true didone, which is the register
 * fashion publishing has actually used for a century, with a real
 * optical-size axis.
 *
 * **Archivo** carries everything else - labels, controls, body copy. A
 * neutral grotesque with both a weight axis running the full 100 to 900 and
 * a width axis.
 *
 * **This replaced Playfair Display and Space Grotesk on 2026-10-29, at the
 * product owner's request, and the reason is worth keeping.** They asked for
 * that pairing, saw it rendered, and said it read as AI-generated. They were
 * right, and it is documented why: a warm-cream ground under a high-contrast
 * serif display is the single most recognisable generated-page palette, and
 * Space Grotesk is specifically named as the "safe" face such pages reach
 * for. Shipping both put this app inside that cluster.
 *
 * The replacement is not a lateral swap. It buys two things neither previous
 * pairing had:
 *
 * * **An optical-size axis on the display face.** Measured: Bodoni Moda
 *   carries `opsz` 6-96. Playfair has none, which was recorded as a real
 *   loss when it replaced Bodoni; this recovers it. A didone's contrast is
 *   only correct at the size it was cut for, so a heading is now drawn with
 *   the cut it would have been given in metal.
 * * **The weights the brief actually asked for.** The brief wanted radical
 *   contrast - 100/200 against 800/900 - and that had to be reported as
 *   impossible, because Playfair stops at 400 and Space Grotesk at 300.
 *   Archivo runs 100 to 900, so for the first time the thing that was asked
 *   for can be built.
 */
/**
 * The display face.
 *
 * A Bodoni italic was added here and then removed. It was set on the welcome
 * strapline and on the sign-in line, and both are gone — the strapline
 * because it was the same words the welcome screen had just shown, and the
 * sign-in line because a didone italic at body length could not be read:
 * the thin strokes of a didone are hairlines, and a hairline on a grained
 * ground is a guess. Left out rather than left exported, so the next person
 * does not find a tempting function with no working use.
 */
export const Display = { variable: 'BodoniModa' } as const;
export const Label = { variable: 'Archivo' } as const;

/**
 * The only weights either face may be set at.
 *
 * No mediums, which is the whole of the brief's "radical contrast": the
 * middle of a weight range is what makes a type system look unconsidered, so
 * it is a compile error here rather than a convention somebody remembers.
 *
 * Measured from the files rather than assumed. Bodoni Moda runs 400-900, so
 * 400 is its lightest and reads as the hairline a display size wants.
 * Archivo runs 100-900, so the label face finally spans the range the brief
 * named: 200 for a whisper, 400 for reading, 800 for a label that has to
 * hold its own beside a didone heading.
 */
export type DisplayWeight = 400 | 900;
export type LabelWeight = 200 | 400 | 800;

/** The range `opsz` actually accepts on Bodoni Moda. Outside it, it clamps. */
export const OpticalSize = { min: 6, max: 96 } as const;

type VariableType = {
  fontFamily: string;
  fontSize: number;
  fontVariationSettings: Readonly<Record<string, number>>;
};

/**
 * Tracking that tightens as type grows.
 *
 * A serif set at 56px with the spacing it was drawn for at 17px looks like
 * body copy somebody enlarged. The standard editorial correction, and a curve
 * rather than a constant: nothing below 24px is touched, and the largest
 * headings come in about a percent and a half.
 */
function opticalTracking(fontSize: number): number {
  if (fontSize < 24) return 0;
  return -Math.round(fontSize * 0.015 * 10) / 10;
}

/**
 * A display heading in Bodoni Moda, cut for the size it is set at.
 *
 * `opsz` takes the pixel size directly, which is the entire point of the
 * axis: at 11pt a didone's hairlines must be thick enough to survive, and at
 * 56px those same hairlines read as clumsy. Weight travels the same way
 * rather than through `fontWeight`, because with a variable font the weight
 * is an axis and `fontWeight` invites the platform to synthesise one.
 */
/**
 * Leading for the display face: a fixed lead over the size, not a ratio.
 *
 * Ratios are wrong at both ends of a display scale. 1.2 is comfortable at 24
 * and absurd at 92, where four points of air is already generous; a flat
 * multiplier either loosens the big sizes or crushes the small ones. A
 * constant added to a shallow slope is how a metal type scale was actually
 * leaded, and it matches the values every call site had hand-tuned: 24 -> 28,
 * 40 -> 44, 56 -> 61, 92 -> 98.
 */
function displayLeading(fontSize: number): number {
  return Math.round(fontSize * 1.04 + 2.6);
}

export function displayType(
  fontSize: number,
  weight: DisplayWeight = 400,
): VariableType & { letterSpacing: number; lineHeight: number } {
  return {
    fontFamily: Display.variable,
    fontSize,
    letterSpacing: opticalTracking(fontSize),
    /**
     * **Returned, not left to the caller.** `ThemedText` applies a per-type
     * style that already sets `lineHeight` from the *body* size, and a
     * caller spreading `displayType(30)` over it changes the size and
     * inherits a 25pt lead. Wrapped lines then overlap and the next line's
     * ascenders cut straight through the one above — which is what happened
     * on the sign-in screen, with no error, no warning and no failing test.
     *
     * Four call sites were missing their own value when this was added. A
     * caller that sets `lineHeight` after the spread still wins, so the
     * hand-tuned ones are untouched.
     */
    lineHeight: displayLeading(fontSize),
    fontVariationSettings: {
      opsz: Math.min(OpticalSize.max, Math.max(OpticalSize.min, fontSize)),
      wght: weight,
    },
  };
}

/**
 * Body copy, controls and labels in Archivo.
 *
 * One caveat worth knowing rather than discovering: Archivo's default
 * instance is its **SemiBold 600**, so anywhere `fontVariationSettings` is
 * unsupported - Android below API 26, a 2017 floor - every weight renders
 * semibold rather than wrong. Every call here sets `wght` explicitly, so
 * that only happens on an engine that ignores the axis entirely.
 */
export function labelType(fontSize: number, weight: LabelWeight = 400): VariableType {
  return {
    fontFamily: Label.variable,
    fontSize,
    fontVariationSettings: { wght: weight },
  };
}

/**
 * The heavy label: the other half of the contrast pair.
 *
 * Section headings and eyebrows - anything that sits next to a light Bodoni
 * heading and has to hold its own against it.
 *
 * **Sentence case, not uppercase.** Tracked-out caps above every heading is
 * one of the most reliable tells of a templated page, and on a narrow tile it
 * is also the congestion: a short phrase in caps with extra tracking wraps to
 * two lines where sentence case fits on one.
 */
export function capsLabel(fontSize: number = 11): VariableType & {
  letterSpacing: number;
} {
  return { ...labelType(fontSize, 800), letterSpacing: 0.2 };
}

/**
 * Monospace, the one place neither face has an answer.
 *
 * Neither Bodoni Moda nor Archivo has a monospaced cut, and `code` exists
 * only for strings that must not be re-spaced. A third bundled file for a
 * handful of technical values would cost more than it buys.
 */
export const Mono = Platform.select({
  ios: 'ui-monospace',
  default: 'monospace',
  web: 'ui-monospace, SFMono-Regular, Menlo, monospace',
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
 * The smallest touchable area, per Apple's 44pt and Material's 48dp.
 *
 * Applied as `minHeight`/`minWidth` or via `hitSlop` on anything smaller than
 * this visually.
 */
/**
 * Grounds for a monogram, when somebody has no photograph.
 *
 * **Eight, and the same one every time for the same person.** A random
 * colour per render makes one account look like several; a single tint
 * for everybody makes a list of monograms unreadable, which is exactly
 * the list where you are scanning for one person. Picked from the id,
 * so it survives a rename and agrees across screens.
 *
 * Chosen light enough to take the text colour the rest of the app uses
 * rather than white: a letter in white on a mid tint is the one
 * contrast failure this component could ship.
 */
export const MonogramTints = [
  '#F2A3A3',
  '#F4C38C',
  '#E8D98A',
  '#AFD4A5',
  '#9CCFD0',
  '#A8BEE8',
  '#C7AEE0',
  '#EFB0C8',
] as const;

/** The same person, the same ground, on every screen. */
export function tintFor(key: string): string {
  let hash = 0;
  for (let index = 0; index < key.length; index += 1) {
    hash = (hash * 31 + key.charCodeAt(index)) % 100003;
  }
  return MonogramTints[hash % MonogramTints.length];
}

export const TapTarget = 44;

/**
 * The layout grid.
 *
 * Every step from `two` up is a multiple of 8, so the 8-point grid the brief
 * asks for is the grid the app lays out on: 8, 16, 24, 32, 64. `three` (16)
 * is the screen edge padding and `four` (24) separates sections.
 *
 * `half` (2) and `one` (4) are deliberately *not* layout values. They are the
 * optical half-steps — the gap inside a badge, the lift under a pill — where
 * 8 would be a visible gutter rather than a nudge. Keeping them named is what
 * stops those places reaching for a raw 3 or 6, which is how a grid actually
 * erodes: not by a redesign, but one hardcoded number at a time.
 */
export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

/**
 * How much of the screen each surface is allowed to be: the 60/30/10 rule.
 *
 * Not a token anything imports — the colours already exist on `Colors`. It is
 * recorded as the proportion each one is *for*, because 60/30/10 is a rule
 * about area, and an area rule that lives only in somebody's head is the one
 * that gets broken by a single enthusiastic screen.
 *
 * * **60, `background`** - warm paper. The ground almost everything sits on.
 * * **30, `backgroundElement`** - raised surfaces: cards, sheets, input
 *   wells, the selected state behind a chip.
 * * **10, `accent`** - burgundy. Primary actions and active states only,
 *   never decoration, and never the background of anything larger than a
 *   control. A full-bleed burgundy panel is the single fastest way to turn a
 *   10 into a 40.
 */
export const SurfaceProportion = {
  page: 60,
  element: 30,
  accent: 10,
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
 * The spring a pin opens with.
 *
 * **Tuned by settling time, not by feel.** A spring's constants do
 * not say how long it takes; the damping ratio and the natural
 * frequency do, and reading three numbers tells you nothing about
 * either. These work out at a damping ratio of 0.54 - under critical,
 * so it overshoots about 13% and lands with the small bounce that
 * reads as "crisp" rather than merely quick - and a settling time of
 * roughly 165ms.
 *
 * The first version of this settled in 369ms, which with the screen
 * transition in front of it came to about half a second and was
 * reported as slow. Keep any change under 200ms:
 *
 *     settling ≈ 4 / (ζ · ω),  ω = √(stiffness/mass),
 *                              ζ = damping / (2·√(stiffness·mass))
 */
export const Pop = { mass: 0.35, stiffness: 700, damping: 17 } as const;

/** Where a tile starts before it springs up to full size. */
export const PopFrom = 0.94;

/**
 * How a photograph appears, for `expo-image`'s `transition` prop.
 *
 * **`skipOnCacheHit` is the whole point of having this as a token.** A
 * bare duration makes the fade play on every appearance, and expo-image
 * documents what that looks like: an already-cached picture
 * "re-animating on every mount, tab change, or scroll back into view".
 * On a board of a hundred and twenty pins, scrolling back up re-faded
 * every tile that was already on disk - which reads as the grid
 * flickering rather than as anything appearing.
 *
 * So the fade is for one thing only: softening a picture arriving over
 * the network for the first time. Anything already cached is simply
 * there, which is what somebody scrolling back expects to find.
 *
 * Pass it straight through: `transition={ImageFade}`.
 */
export const ImageFade = {
  duration: Motion.fast,
  skipOnCacheHit: 'all',
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
  /**
   * The avatar box *before* its picture has loaded.
   *
   * 1:2 because that is what `muse-image-1.0` measured at for the avatar
   * prompt: 1120 x 2240. It is only a starting height — the figure reads the
   * real ratio off the loaded image and resizes to it, because the generator
   * does not return a consistent shape (the same model returns 1280 x 1920
   * for the Discover covers) and a hardcoded ratio is how a person gets
   * squashed.
   */
  avatar: 1 / 2,
  /**
   * The taller of the two masonry steps. Also the covers' native ratio, so a
   * tile at this height is the uncropped picture.
   */
  tall: 2 / 3,
  /** Short-form community video. */
  reel: 9 / 16,
} as const;

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
