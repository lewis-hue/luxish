/**
 * The palette is a product requirement, not a preference: §3 of the brief asks for
 * sufficient contrast, and a token file is the only place that can be checked once
 * for the whole app. These tests fail the build if a colour edit breaks legibility.
 */

import {
  AspectRatio,
  Colors,
  FontSize,
  MinFontSize,
  Motion,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';

/** WCAG 2.1 relative luminance. Implemented here rather than pulled in as a dep. */
function relativeLuminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not an opaque 6-digit hex colour: ${hex}`);
  const int = parseInt(m[1], 16);
  const channels = [(int >> 16) & 0xff, (int >> 8) & 0xff, int & 0xff].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(a: string, b: string): number {
  const [la, lb] = [relativeLuminance(a), relativeLuminance(b)];
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

const SCHEMES = ['light', 'dark'] as const;

describe('contrast', () => {
  /** 4.5:1 is the AA threshold for body text. */
  it.each(SCHEMES)('%s: primary text on both surfaces meets AA', (scheme) => {
    const c = Colors[scheme];
    expect(contrastRatio(c.text, c.background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(c.text, c.backgroundElement)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(SCHEMES)('%s: secondary text meets AA on the base surface', (scheme) => {
    const c = Colors[scheme];
    expect(contrastRatio(c.textSecondary, c.background)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(SCHEMES)('%s: accent text on the accent surface meets AA', (scheme) => {
    const c = Colors[scheme];
    expect(contrastRatio(c.accentText, c.accent)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(SCHEMES)('%s: accent is legible as text on the base surface', (scheme) => {
    // The accent doubles as a link/affordance colour, so it needs AA too.
    const c = Colors[scheme];
    expect(contrastRatio(c.accent, c.background)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(SCHEMES)('%s: danger is legible on the base surface', (scheme) => {
    const c = Colors[scheme];
    expect(contrastRatio(c.danger, c.background)).toBeGreaterThanOrEqual(4.5);
  });
});

describe('scheme parity', () => {
  it('defines exactly the same keys in light and dark', () => {
    // A key present in one scheme only crashes at runtime in the other.
    expect(Object.keys(Colors.light).sort()).toEqual(Object.keys(Colors.dark).sort());
  });
});

describe('scales', () => {
  it('keeps spacing on the 4-point grid', () => {
    for (const [name, value] of Object.entries(Spacing)) {
      // `half` (2) is the documented sub-grid hairline exception.
      if (name === 'half') continue;
      expect(value % 4).toBe(0);
    }
  });

  it('orders spacing ascending so steps are substitutable', () => {
    const values = Object.values(Spacing);
    expect([...values].sort((a, b) => a - b)).toEqual(values);
  });

  it('orders motion durations ascending and keeps them restrained', () => {
    expect(Motion.fast).toBeLessThan(Motion.base);
    expect(Motion.base).toBeLessThan(Motion.slow);
    // Anything past ~400ms reads as sluggish on a mid-range Android device.
    expect(Motion.slow).toBeLessThanOrEqual(400);
  });

  it('exposes a capsule radius and an ascending non-capsule ramp', () => {
    expect(Radius.sm).toBeLessThan(Radius.md);
    expect(Radius.md).toBeLessThan(Radius.lg);
    expect(Radius.full).toBeGreaterThan(1000);
  });

  it('keeps every image ratio portrait', () => {
    // Grid alignment depends on these being fixed, not per-screen. Garment is
    // 2:3 rather than square because a square cell crops a coat or a dress
    // around the knee, and the wardrobe is the user's own clothes.
    expect(AspectRatio.editorial).toBeLessThan(1);
    expect(AspectRatio.garment).toBeCloseTo(3 / 4);
    expect(AspectRatio.garment).toBeLessThan(1);
    expect(AspectRatio.reel).toBeLessThan(AspectRatio.editorial);
  });

  it('keeps the semantic colours legible on both grounds', () => {
    // AA for text. These carry meaning, so they must be readable, not merely
    // present.
    for (const scheme of ['light', 'dark'] as const) {
      for (const token of ['success', 'warning', 'danger'] as const) {
        expect(contrastRatio(Colors[scheme][token], Colors[scheme].background)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(Colors[scheme][token], Colors[scheme].backgroundElement)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('gives control boundaries the 3:1 that WCAG 1.4.11 requires', () => {
    // `border` is a divider and is allowed to be faint. `borderStrong` bounds
    // inputs and outlined buttons, where the boundary IS the affordance, so it
    // has to clear the non-text contrast minimum.
    for (const scheme of ['light', 'dark'] as const) {
      expect(contrastRatio(Colors[scheme].borderStrong, Colors[scheme].background)).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(Colors[scheme].border, Colors[scheme].background)).toBeLessThan(3);
    }
  });

  it('keeps the semantic colours warm rather than stock', () => {
    // A stock #00C853 green or #2196F3 blue would be the one cold thing on a
    // warm page and reads immediately as a dropped-in component library. There
    // is deliberately no `info` token for the same reason.
    expect(Colors.light).not.toHaveProperty('info');
    expect(Colors.dark).not.toHaveProperty('info');
    for (const scheme of ['light', 'dark'] as const) {
      for (const token of ['success', 'warning'] as const) {
        const hue = hueOf(Colors[scheme][token]);
        // Warm half of the wheel: red through yellow-green.
        expect(hue).toBeGreaterThanOrEqual(20);
        expect(hue).toBeLessThanOrEqual(100);
      }
    }
  });

  it('never allows type below the platform legibility floor', () => {
    // iOS Caption 2 is 11pt and is the smallest built-in text style.
    expect(MinFontSize).toBe(11);
    for (const size of Object.values(FontSize)) {
      expect(size).toBeGreaterThanOrEqual(MinFontSize);
    }
    expect(Math.min(...Object.values(FontSize))).toBe(MinFontSize);
  });

  it('meets the platform minimum tap target', () => {
    // Apple 44pt, Material 48dp.
    expect(TapTarget).toBeGreaterThanOrEqual(44);
  });
});

/** Hue in degrees, for asserting a colour is warm rather than stock. */
function hueOf(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max === min) return 0;
  const d = max - min;
  const h =
    max === r ? ((g - b) / d + (g < b ? 6 : 0)) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return h * 60;
}
