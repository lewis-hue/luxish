/**
 * The bar reads what somebody is doing, not which screen is open.
 *
 * A fit's page opens as one photograph filling the screen, and five
 * navigation chips across the bottom sit on it. Scroll past the
 * picture and the same page is a grid of other fits, where the chips
 * are the useful thing. One route, two postures.
 */
import {
  ALWAYS_SHOWN_ABOVE,
  AT_REST,
  BROWSING_BEGINS_AT,
  HIDE_AFTER,
  JITTER,
  REVEAL_AFTER,
  STEADY_BAND,
  focusesFirst,
  immersed,
  scrolled,
} from '@/features/navigation/attention';

/** A full-length cover on a tall phone. */
const HERO = 700;
const MARK = HERO * BROWSING_BEGINS_AT;

describe('immersed', () => {
  it('keeps the screen at the top of a pin', () => {
    // The picture is the whole point and nothing should sit on it.
    expect(immersed({ offsetY: 0, focusHeight: HERO, was: false })).toBe(true);
  });

  it('lets go once somebody has scrolled into what else there is', () => {
    expect(
      immersed({ offsetY: HERO + 200, focusHeight: HERO, was: true }),
    ).toBe(false);
  });

  it('comes back when somebody scrolls up to the picture again', () => {
    expect(immersed({ offsetY: 0, focusHeight: HERO, was: false })).toBe(true);
  });

  it('does not flip inside the steady band', () => {
    // A finger resting on the threshold, or the bounce at the end of
    // a flick, crosses one line repeatedly - and the bar would drop
    // and rise several times a second.
    const justBelow = MARK - STEADY_BAND / 4;
    const justAbove = MARK + STEADY_BAND / 4;

    // Already immersed: neither nudge releases it.
    expect(immersed({ offsetY: justBelow, focusHeight: HERO, was: true })).toBe(true);
    expect(immersed({ offsetY: justAbove, focusHeight: HERO, was: true })).toBe(true);

    // Already browsing: neither nudge re-immerses it.
    expect(immersed({ offsetY: justAbove, focusHeight: HERO, was: false })).toBe(false);
    expect(immersed({ offsetY: justBelow, focusHeight: HERO, was: false })).toBe(false);
  });

  it('takes a real movement to change its mind either way', () => {
    // Past the top of the band, browsing starts whatever it was.
    expect(
      immersed({ offsetY: MARK + STEADY_BAND, focusHeight: HERO, was: true }),
    ).toBe(false);
    // Back under the bottom of it, the picture has the screen again.
    expect(
      immersed({ offsetY: MARK - STEADY_BAND, focusHeight: HERO, was: false }),
    ).toBe(true);
  });

  it('scales with the picture rather than using one number', () => {
    // The hero is as tall as the photograph in it, so a fixed
    // threshold would be most of a wide picture and a sliver of a
    // tall one.
    const shortHero = 300;
    const atShort = immersed({ offsetY: 280, focusHeight: shortHero, was: true });
    const atTall = immersed({ offsetY: 280, focusHeight: 900, was: true });
    expect(atShort).toBe(false);
    expect(atTall).toBe(true);
  });

  it('is never immersed on a page with nothing to focus on', () => {
    // A board is for browsing from its first pixel.
    for (const focusHeight of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(immersed({ offsetY: 0, focusHeight, was: true })).toBe(false);
    }
  });

  it('does not go immersed when a list is pulled past its top', () => {
    // Overscroll gives a negative offset, which must not read as
    // anything other than "at the top".
    expect(immersed({ offsetY: -120, focusHeight: HERO, was: false })).toBe(true);
  });
});

describe('focusesFirst', () => {
  it('knows a pin', () => {
    expect(focusesFirst('/fit/abc123')).toBe(true);
  });

  it('leaves every list alone', () => {
    // These want the bar from the first pixel: a board is for
    // browsing, a wardrobe for finding, settings has no hero.
    for (const path of ['/', '/search', '/wardrobe', '/studio', '/profile', '/settings']) {
      expect(focusesFirst(path)).toBe(false);
    }
  });

  it('matches a whole segment, not a prefix of a word', () => {
    expect(focusesFirst('/fitting-room')).toBe(false);
  });
});

// --------------------------------------------------------------------------
// Direction
//
// Scrolling down is reading forward; scrolling back up is heading for
// the way out. The bar follows that rather than sitting there always.
// --------------------------------------------------------------------------

/** Feed a run of positions through, returning the final state. */
function run(from = AT_REST, ...positions: number[]) {
  return positions.reduce(scrolled, from);
}

describe('the bar follows which way you are going', () => {
  it('is shown at the top of the page', () => {
    expect(run(AT_REST, 0, 10, 20).hidden).toBe(false);
  });

  it('stands down once you have scrolled down deliberately', () => {
    const end = run(AT_REST, 200, 200 + HIDE_AFTER + 10);
    expect(end.hidden).toBe(true);
  });

  it('comes back the moment you scroll up', () => {
    const down = run(AT_REST, 400, 400 + HIDE_AFTER + 10);
    expect(down.hidden).toBe(true);
    const up = scrolled(down, down.lastY - REVEAL_AFTER - 1);
    expect(up.hidden).toBe(false);
  });

  it('reveals sooner than it hides', () => {
    // **The costs are asymmetric.** A bar that hides too eagerly
    // flickers; one that reveals too eagerly shows a bar nobody
    // minds. This is that judgement, as a number.
    expect(REVEAL_AFTER).toBeLessThan(HIDE_AFTER);
  });

  it('ignores a finger resting on the glass', () => {
    const start = run(AT_REST, 400, 400 + HIDE_AFTER + 10);
    const jittered = run(start, start.lastY + JITTER - 1, start.lastY);
    expect(jittered.hidden).toBe(true);
  });

  it('does not let a wobble accumulate across the threshold', () => {
    // Down a little, up a little, repeatedly. Without resetting the
    // count on a turn this would add up to a hide.
    let state = run(AT_REST, 300);
    for (let i = 0; i < 20; i += 1) {
      state = scrolled(state, 300 + (i % 2 ? 20 : 0));
    }
    expect(state.hidden).toBe(false);
  });

  it('is shown again near the top however it got there', () => {
    const down = run(AT_REST, 500, 500 + HIDE_AFTER + 10);
    expect(down.hidden).toBe(true);
    expect(scrolled(down, ALWAYS_SHOWN_ABOVE - 1).hidden).toBe(false);
  });

  it('is shown when the list bounces past the top', () => {
    const down = run(AT_REST, 500, 500 + HIDE_AFTER + 10);
    expect(scrolled(down, -40).hidden).toBe(false);
  });
});
