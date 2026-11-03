/**
 * How long ago, in the shortest true form.
 *
 * Pinned because the failure is cosmetic but constant: an inbox that says
 * "just now" and then "1 minute ago" a moment later reads as a stopwatch
 * rather than a list, and rounding errors at the unit boundaries are exactly
 * where that shows up.
 */

import { timeAgo } from '@/api/queries/notifications';

const NOW = new Date('2026-10-29T12:00:00.000Z');

function ago(ms: number): string {
  return timeAgo(new Date(NOW.getTime() - ms).toISOString(), NOW);
}

describe('timeAgo', () => {
  it('says just now under a minute', () => {
    expect(ago(0)).toBe('just now');
    expect(ago(20_000)).toBe('just now');
  });

  it('counts minutes up to an hour', () => {
    expect(ago(5 * 60_000)).toBe('5m ago');
    expect(ago(59 * 60_000)).toBe('59m ago');
  });

  it('switches to hours at an hour', () => {
    expect(ago(60 * 60_000)).toBe('1h ago');
    expect(ago(23 * 3600_000)).toBe('23h ago');
  });

  it('switches to days at a day', () => {
    expect(ago(24 * 3600_000)).toBe('1d ago');
    expect(ago(13 * 24 * 3600_000)).toBe('13d ago');
  });

  it('never reports a negative age', () => {
    // A device whose clock is ahead of the server's would otherwise show
    // "-3m ago", which reads as a bug in the app rather than in the clock.
    expect(ago(-90_000)).toBe('just now');
  });

  it('returns nothing for a value it cannot read', () => {
    expect(timeAgo('not a date', NOW)).toBe('');
  });
});
