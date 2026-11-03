/**
 * What you arrange is what gets posted.
 *
 * The complaint: "the collage canvas needs to be the shape of the pin
 * shells in the discovery tab so that when posted it fits well in the
 * shell." The canvas was 4:5 at the time, under a comment asserting
 * that was the app's shape. It was not, and the two had drifted - so
 * a collage was composed in one frame and shown in another, cropped
 * at exactly the edges somebody had spent their time arranging.
 *
 * These tests couple the two modules rather than restating either.
 * `canvasBox` knows nothing about `clampShape` and `clampShape` knows
 * nothing about collages; if either moves, the coupling test fails
 * and says which claim stopped being true.
 */

import { canvasBox, canvasShape } from '@/features/collage/box';
import { SHAPE, UNKNOWN_SHAPE, clampShape } from '@/features/feed/shape';

/** An iPhone 17 Pro Max in points, and a small phone. */
const WIDE = 440;
const NARROW = 320;

describe('canvasBox', () => {
  it('reads the shape from the app rather than from its own constant', () => {
    // **This is the assertion that catches the bug that happened.**
    // The canvas was 4:5 - which is *within* the shell's bounds, so
    // any "is it in range" check passes on it and says nothing. What
    // was wrong was that it was a second answer to a question the
    // app had already answered: 4:5 next to 3:4 is a card visibly
    // the wrong shape beside every other card, which is the entire
    // thing `feed/shape.ts` exists to prevent.
    //
    // So what is pinned is that there is one source of the shape. If
    // somebody reintroduces a literal here, this fails.
    expect(canvasShape()).toBe(UNKNOWN_SHAPE);
    expect(canvasShape()).not.toBe(4 / 5);
  });

  it('needs no reshaping on the way to the board', () => {
    // Weaker than the above and kept for what it does cover: the
    // server stands a posted picture upright, and a canvas outside
    // the bounds would be reshaped after somebody arranged it.
    expect(clampShape(canvasShape())).toBe(canvasShape());
  });

  it('is upright, like every other pin', () => {
    const box = canvasBox(WIDE);
    expect(box.height).toBeGreaterThan(box.width);
  });

  it('sits inside the bounds a card is ever drawn in', () => {
    // Stated against the bounds themselves rather than the one
    // constant, so widening the shell cannot silently orphan this.
    expect(canvasShape()).toBeGreaterThanOrEqual(SHAPE.tallest);
    expect(canvasShape()).toBeLessThanOrEqual(SHAPE.widest);
  });

  it('keeps that shape on any screen', () => {
    for (const width of [NARROW, 390, WIDE, 1024]) {
      const box = canvasBox(width);
      expect(box.width / box.height).toBeCloseTo(canvasShape(), 10);
    }
  });

  it('leaves a gutter either side', () => {
    // The canvas is a surface being arranged, not the page. Without
    // an edge there is nothing for a piece dragged to the corner to
    // be dragged to.
    expect(canvasBox(WIDE).width).toBeLessThan(WIDE);
  });

  it('is empty rather than negative before layout', () => {
    // `useWindowDimensions` reports 0 for a frame on some mounts,
    // and a negative width renders as an inverted box.
    expect(canvasBox(0)).toEqual({ width: 0, height: 0 });
    expect(canvasBox(8)).toEqual({ width: 0, height: 0 });
    expect(canvasBox(Number.NaN)).toEqual({ width: 0, height: 0 });
  });
});
