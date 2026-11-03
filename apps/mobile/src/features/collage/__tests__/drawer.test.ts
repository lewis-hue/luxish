/**
 * The picture drawer's two stops.
 *
 * The complaint that started this work was a handle that said it
 * could be pulled and could not: the sheet covered the bottom seventy
 * per cent of the canvas, so the lower half of a collage could not be
 * seen while adding to it. The fix was a gesture, and a gesture is
 * the one part of this that no test can drive - a worklet body runs
 * only under a real touch on a real device.
 *
 * So the decisions were lifted out of the callbacks, and this is what
 * can honestly be checked: that the drawer cannot be left anywhere
 * that is neither stop, that it cannot be pushed off either end, and
 * that a flick is read as a throw rather than as its distance. What
 * remains unverified is how it *feels*, which is a device question.
 */

import {
  FLICK,
  PEEK_FRACTION,
  dragTo,
  isShowingPictures,
  peekFor,
  settleTo,
} from '@/features/collage/drawer';

/** An iPhone 17 Pro Max, which is what this is tested on by hand. */
const SCREEN = 956;
const PEEK = peekFor(SCREEN);

describe('peekFor', () => {
  it('uncovers most of the canvas, not a strip of it', () => {
    // The whole point of the drawer moving is to see the collage
    // under it, so the travel has to be a large part of the screen.
    expect(PEEK).toBeGreaterThan(SCREEN * 0.3);
    expect(PEEK).toBe(Math.round(SCREEN * PEEK_FRACTION));
  });

  it('is a whole number of points', () => {
    // A fractional translate blurs the handle on a 3x screen.
    expect(Number.isInteger(peekFor(1001))).toBe(true);
  });

  it('survives a screen height it cannot use', () => {
    // `useWindowDimensions` reports 0 for a frame before layout.
    expect(peekFor(0)).toBe(0);
    expect(peekFor(Number.NaN)).toBe(0);
  });
});

describe('dragTo', () => {
  it('follows the finger between the stops', () => {
    expect(dragTo(0, 100, PEEK)).toBe(100);
    expect(dragTo(50, 60, PEEK)).toBe(110);
  });

  it('cannot be pulled past the lower stop', () => {
    // Bounded rather than rubber-banded. Reaching the end and
    // stopping is what tells a finger there is no more.
    expect(dragTo(0, PEEK + 500, PEEK)).toBe(PEEK);
  });

  it('cannot be pushed above the top', () => {
    // The sheet's own top edge is the top. Dragging up from closed
    // must not lift it off the screen.
    expect(dragTo(0, -400, PEEK)).toBe(0);
    expect(dragTo(100, -400, PEEK)).toBe(0);
  });

  it('closes rather than jumping on a nonsense translation', () => {
    expect(dragTo(0, Number.NaN, PEEK)).toBe(0);
  });
});

describe('settleTo', () => {
  it('never rests between the two stops', () => {
    // The bug this prevents: a drawer parked at an arbitrary height,
    // which is one somebody has to keep adjusting.
    for (const at of [0, 1, 40, PEEK / 2 - 1, PEEK / 2 + 1, PEEK - 1, PEEK]) {
      expect([0, PEEK]).toContain(settleTo(at, 0, PEEK));
    }
  });

  it('goes to the nearer stop on a slow release', () => {
    expect(settleTo(PEEK * 0.2, 0, PEEK)).toBe(0);
    expect(settleTo(PEEK * 0.8, 0, PEEK)).toBe(PEEK);
  });

  it('follows a flick however far it got', () => {
    // Somebody who flicks down from the top means "out of the way"
    // even though the drawer has barely moved. Reading the distance
    // instead would snap it straight back and read as a dead handle,
    // which is the complaint this whole drawer exists to answer.
    expect(settleTo(10, FLICK + 1, PEEK)).toBe(PEEK);
    expect(settleTo(PEEK - 10, -FLICK - 1, PEEK)).toBe(0);
  });

  it('treats a drag at exactly the flick speed as a drag', () => {
    // Boundary stated rather than left to a reader of `>`: at the
    // threshold the nearer stop wins, so a steady pull that happens
    // to hit 500 does not fly.
    expect(settleTo(10, FLICK, PEEK)).toBe(0);
    expect(settleTo(PEEK - 10, -FLICK, PEEK)).toBe(PEEK);
  });
});

describe('isShowingPictures', () => {
  it('is true only with the drawer fully up', () => {
    expect(isShowingPictures(0)).toBe(true);
    expect(isShowingPictures(1)).toBe(false);
    expect(isShowingPictures(PEEK)).toBe(false);
  });
});
