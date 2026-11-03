/**
 * How long ago a comment was written, beside the name that wrote it.
 *
 * It sits on a line that also carries Reply, a heart and a menu, so it
 * has to be short: `10mo`, not `10 months ago`, which pushes the
 * controls off the edge of a narrow phone.
 */

import { sinceShort } from '@/features/feed/comments';

/** A fixed now, so the test is not about the clock. */
const NOW = new Date('2026-11-01T12:00:00Z');

/** `seconds` ago, as the server would send it. */
function ago(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe('sinceShort', () => {
  it.each([
    ['seconds', 5, '5s'],
    ['just under a minute', 59, '59s'],
    ['a minute', 60, '1m'],
    ['minutes', 42 * 60, '42m'],
    ['an hour', 3600, '1h'],
    ['hours', 5 * 3600, '5h'],
    ['a day', 86_400, '1d'],
    ['days', 3 * 86_400, '3d'],
    ['a week', 604_800, '1w'],
    ['weeks', 3 * 604_800, '3w'],
  ])('writes %s as %s', (_what, seconds, expected) => {
    expect(sinceShort(ago(seconds), NOW)).toBe(expected);
  });

  it('writes months the way the reference does', () => {
    // "10mo" is the form in the reference, and the one everybody reads
    // without thinking about it.
    expect(sinceShort(ago(10 * 2_629_800), NOW)).toBe('10mo');
  });

  it('stops at years rather than counting 36mo', () => {
    expect(sinceShort(ago(2 * 31_557_600), NOW)).toBe('2y');
  });

  it('never goes negative for a clock that is slightly ahead', () => {
    // Phone clocks drift. A comment "written" four seconds from now is
    // a drift, not a comment from the future.
    expect(sinceShort(new Date(NOW.getTime() + 4000).toISOString(), NOW)).toBe('0s');
  });

  it('renders nothing it cannot read', () => {
    // Better than `NaNs` beside somebody's name.
    expect(sinceShort('not a date', NOW)).toBe('');
    expect(sinceShort('', NOW)).toBe('');
  });

  it('stays short enough to sit on the controls line', () => {
    for (const seconds of [1, 90, 7200, 200_000, 3_000_000, 40_000_000, 90_000_000]) {
      expect(sinceShort(ago(seconds), NOW).length).toBeLessThanOrEqual(4);
    }
  });
});
