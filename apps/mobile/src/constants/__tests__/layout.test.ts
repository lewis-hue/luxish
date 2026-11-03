/**
 * The grid, and the rules that keep it a grid.
 *
 * Both of these erode the same way — not in a redesign, but one hardcoded
 * number at a time, each individually reasonable. So they are asserted over
 * the source rather than written down somewhere and hoped for.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { Spacing, SurfaceProportion, displayType } from '@/constants/theme';

const SRC = join(__dirname, '..', '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '__tests__' ? [] : sourceFiles(path);
    return /\.tsx$/.test(entry.name) ? [path] : [];
  });
}

describe('the 8-point grid', () => {
  it('actually reaches the source it claims to check', () => {
    // Without this, a wrong path makes every scan below pass by finding
    // nothing, which is the most comfortable way for a lint-style test to
    // stop working.
    expect(sourceFiles(SRC).length).toBeGreaterThan(20);
  });

  it('puts every layout step on a multiple of 8', () => {
    const layout = [Spacing.two, Spacing.three, Spacing.four, Spacing.five, Spacing.six];
    expect(layout.filter((step) => step % 8 !== 0)).toEqual([]);
  });

  it('keeps the sub-grid to the two optical half-steps', () => {
    // `half` and `one` exist for the gap inside a badge, where 8 would be a
    // gutter. Any third sub-grid value would mean the grid has a third
    // opinion about small spacing, which is the same as having none.
    const sub = Object.values(Spacing).filter((step) => step < 8);
    expect(sub.sort((a, b) => a - b)).toEqual([2, 4]);
  });

  it('is not bypassed by a raw number in any screen or component', () => {
    // The real failure mode. A `paddingVertical: 3` reads as harmless and is
    // how an 8-point grid becomes a 1-point grid over a few months.
    const offenders = sourceFiles(SRC).flatMap((file) => {
      const matches = readFileSync(file, 'utf8').match(
        /\b(?:padding|margin|gap|rowGap|columnGap)[A-Za-z]*: \d+\b/g,
      );
      return (matches ?? []).map((match) => `${file.slice(SRC.length + 1)}: ${match}`);
    });
    expect(offenders).toEqual([]);
  });
});

describe('the display tracking curve', () => {
  it('is not overridden by a hand-tuned value next to it', () => {
    // `displayType()` returns its own `letterSpacing`, so a style object that
    // spreads it and then sets `letterSpacing` silently wins. That is how the
    // app ended up with four headings at four hand-tuned values — the exact
    // inconsistency the curve exists to remove, and invisible in review
    // because both lines look deliberate.
    const offenders = sourceFiles(SRC).flatMap((file) => {
      const source = readFileSync(file, 'utf8');
      const matches = source.match(/\.\.\.displayType\([^)]*\)[^}]*letterSpacing/g);
      return (matches ?? []).map(() => file.slice(SRC.length + 1));
    });
    expect(offenders).toEqual([]);
  });
});

describe('the 60/30/10 split', () => {
  it('describes a whole screen', () => {
    const total = SurfaceProportion.page + SurfaceProportion.element + SurfaceProportion.accent;
    expect(total).toBe(100);
  });

  it('never makes the accent a page background', () => {
    // 10 is the accent's whole budget, and a full-bleed burgundy panel spends
    // it several times over. The accent belongs on controls and active
    // states; `backgroundElement` is what a surface is for.
    const offenders = sourceFiles(SRC).flatMap((file) => {
      const matches = readFileSync(file, 'utf8').match(/backgroundColor: colors\.accent/g);
      const source = readFileSync(file, 'utf8');
      return (matches ?? []).flatMap((match) => {
        // A control may be accent-filled; a scroll container may not.
        const index = source.indexOf(match);
        const context = source.slice(Math.max(0, index - 600), index);
        const isContainer = /<(ScrollView|FlatList|SafeAreaView)\b[^>]*$/.test(context);
        return isContainer ? [`${file.slice(SRC.length + 1)}: ${match}`] : [];
      });
    });
    expect(offenders).toEqual([]);
  });
});

/**
 * The display face carries its own leading.
 *
 * `ThemedText` applies a per-type style that sets `lineHeight` from the body
 * size. A caller spreading `displayType(30)` over that changed the size and
 * inherited a 25pt lead, so wrapped lines overlapped and the next line's
 * ascenders cut through the one above. It threw nothing, warned nothing and
 * failed no test — it was reported by somebody looking at the screen.
 */
describe('display leading', () => {
  it('always leaves room for the glyphs', () => {
    for (let size = 16; size <= 96; size += 1) {
      const { fontSize, lineHeight } = displayType(size);
      expect(fontSize).toBe(size);
      // Overlapping lines is the whole failure. Anything at or below the
      // font size guarantees it.
      expect(lineHeight).toBeGreaterThan(size);
    }
  });

  it('tightens as the size grows, the way a type scale is leaded', () => {
    // A flat ratio is wrong at both ends: comfortable at 24 and absurd at
    // 92. The lead-over-size shrinks as a proportion.
    const small = displayType(24);
    const large = displayType(92);
    expect(small.lineHeight / small.fontSize).toBeGreaterThan(
      large.lineHeight / large.fontSize,
    );
  });

  it('matches the values the call sites had hand-tuned', () => {
    // These were written out by hand across the app before the function
    // returned a lineHeight at all. The curve has to agree with them, or
    // adding it silently restyles every heading in the product.
    expect(displayType(24).lineHeight).toBe(28);
    expect(displayType(32).lineHeight).toBe(36);
    expect(displayType(40).lineHeight).toBe(44);
  });
});
