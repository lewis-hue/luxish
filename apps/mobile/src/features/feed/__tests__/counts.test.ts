/**
 * A count, short enough to sit in a row of controls.
 *
 * The screenshot shows "1.6K" under a fit, not "1,632". The rounding
 * is the whole behaviour, and the boundaries are where it goes wrong.
 */

import { compactCount } from '@/features/feed/counts';

describe('compactCount', () => {
  it('keeps a small number exactly', () => {
    expect(compactCount(0)).toBe('0');
    expect(compactCount(7)).toBe('7');
    expect(compactCount(999)).toBe('999');
  });

  it('turns a thousand into a thousand, not 1.0K', () => {
    // A trailing zero after a decimal point is a digit that says
    // nothing and takes the same room as one that does.
    expect(compactCount(1000)).toBe('1K');
    expect(compactCount(2000)).toBe('2K');
  });

  it('keeps one decimal while it is a real difference', () => {
    expect(compactCount(1632)).toBe('1.6K');
    expect(compactCount(9700)).toBe('9.7K');
  });

  it('rounds down rather than up', () => {
    // 1699 saves is not 1.7K yet. Overstating a count on somebody's
    // own fit is the one direction that reads as a lie.
    expect(compactCount(1699)).toBe('1.6K');
  });

  it('drops the decimal once it is noise', () => {
    // "47.3K" is three characters for a distinction nobody acts on.
    expect(compactCount(10_000)).toBe('10K');
    expect(compactCount(47_300)).toBe('47K');
    expect(compactCount(999_999)).toBe('999K');
  });

  it('goes to millions rather than a four-digit K', () => {
    expect(compactCount(1_000_000)).toBe('1M');
    expect(compactCount(1_640_000)).toBe('1.6M');
    expect(compactCount(12_000_000)).toBe('12M');
  });

  it('never grows past five characters', () => {
    // What the row was shortened for: the controls beside it.
    for (const n of [0, 999, 1000, 9999, 10_000, 999_999, 1_000_000, 99_900_000]) {
      expect(compactCount(n).length).toBeLessThanOrEqual(5);
    }
  });
});
