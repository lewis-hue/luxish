/**
 * The palette is a product requirement, not a preference: §3 of the brief asks for
 * sufficient contrast, and a token file is the only place that can be checked once
 * for the whole app. These tests fail the build if a colour edit breaks legibility.
 */

import { AspectRatio, Colors, Motion, Radius, Spacing } from '@/constants/theme';

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

  it('defines portrait editorial and square garment ratios', () => {
    // Grid alignment depends on these being fixed, not per-screen.
    expect(AspectRatio.editorial).toBeLessThan(1);
    expect(AspectRatio.garment).toBe(1);
    expect(AspectRatio.reel).toBeLessThan(AspectRatio.editorial);
  });
});
