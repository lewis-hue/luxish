/**
 * The reminder schedule, as arithmetic.
 *
 * The scheduling call itself is expo's to test; what is ours is which
 * reminders a set of plans deserves, and the three ways that quietly goes
 * wrong: reminding about the past, reminding beyond the horizon, and a
 * date string surviving a timezone.
 */

import { remindersFor } from '@/features/notifications/plan-reminders';

/** Tuesday 3 November 2026, 12:00 local. */
const NOW = new Date(2026, 10, 3, 12, 0, 0);

const plan = (plannedFor: string, note: string | null = null) => ({
  plannedFor,
  // A plan is the clothes somebody owns now, not a catalogue entry.
  garmentIds: ['g-blazer', 'g-shirt'],
  note,
});

describe('remindersFor', () => {
  it('schedules the morning of each upcoming plan', () => {
    const out = remindersFor([plan('2026-11-05')], NOW);
    expect(out).toHaveLength(1);
    expect(out[0].date.getFullYear()).toBe(2026);
    expect(out[0].date.getMonth()).toBe(10);
    expect(out[0].date.getDate()).toBe(5);
    expect(out[0].date.getHours()).toBe(7);
    expect(out[0].date.getMinutes()).toBe(30);
  });

  it('never reminds about a morning that has already passed', () => {
    // Today's 7:30 was hours ago at noon; scheduling it would fire the
    // notification immediately, which is noise about the past.
    expect(remindersFor([plan('2026-11-03')], NOW)).toEqual([]);
    expect(remindersFor([plan('2026-11-01')], NOW)).toEqual([]);
  });

  it('stops at the week the planner itself shows', () => {
    expect(remindersFor([plan('2026-11-20')], NOW)).toEqual([]);
  });

  it('reads the date as a local day, not an instant', () => {
    // The whole reason plans cross the wire as YYYY-MM-DD: parsed as UTC
    // and converted, a Thursday plan becomes Wednesday night for anybody
    // west of Greenwich. Local construction keeps the day the day.
    const out = remindersFor([plan('2026-11-04')], NOW);
    expect(out[0].date.getDate()).toBe(4);
  });

  it('uses the note as the line when there is one', () => {
    const noted = remindersFor([plan('2026-11-05', 'Review meeting')], NOW);
    expect(noted[0].body).toBe('Review meeting');
    const bare = remindersFor([plan('2026-11-05')], NOW);
    expect(bare[0].body).toBe('2 pieces laid out.');
  });

  it('sorts by morning, soonest first', () => {
    const out = remindersFor([plan('2026-11-08'), plan('2026-11-04')], NOW);
    expect(out.map((reminder) => reminder.date.getDate())).toEqual([4, 8]);
  });

  it('skips a malformed date rather than throwing', () => {
    expect(remindersFor([plan('not-a-day')], NOW)).toEqual([]);
  });

  it('says nothing about a day with no clothes laid out', () => {
    // A plan can exist with a note and nothing chosen while somebody is
    // still deciding. A notification about an empty day is noise.
    const empty = { plannedFor: '2026-11-05', garmentIds: [], note: 'Think' };
    expect(remindersFor([empty], NOW)).toEqual([]);
  });

  it('counts one piece as one', () => {
    const one = { plannedFor: '2026-11-05', garmentIds: ['g-coat'], note: null };
    expect(remindersFor([one], NOW)[0].body).toBe('1 piece laid out.');
  });
});
