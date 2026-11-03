/**
 * The chart caption, which replaces an axis and therefore must not lie
 * about which day it names.
 */

import { bestDayLine } from '@/api/queries/studio';

/** Tuesday 3 November 2026. */
const NOW = new Date(2026, 10, 3, 12, 0, 0);

describe('bestDayLine', () => {
  it('names the peak day and its count', () => {
    // Peak of 7, two days before now.
    const series = [0, 1, 7, 0, 2];
    const line = bestDayLine(series, NOW);
    expect(line).toContain('7 touches');
    expect(line).toContain('November');
    expect(line).toContain('1');
  });

  it('prefers the most recent of tied peaks', () => {
    const line = bestDayLine([3, 0, 3], NOW);
    // The tie resolves to today, not two days ago. Locale decides the
    // ordering of day and month, so the test pins the facts only.
    expect(line).toContain('November');
    expect(line).toContain('3');
    expect(line).not.toContain('November 1');
    expect(line).not.toContain('1 November');
  });

  it('says nothing over a silent window', () => {
    expect(bestDayLine([0, 0, 0], NOW)).toBeNull();
    expect(bestDayLine([], NOW)).toBeNull();
  });

  it('speaks in the singular for a single touch', () => {
    expect(bestDayLine([1], NOW)).toContain('1 touch.');
  });
});
