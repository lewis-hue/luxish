/**
 * The composition the product opens on.
 *
 * This file used to test a stored "has this device seen the introduction"
 * flag. That flag is gone: every feature sits behind sign-in, so a signed-out
 * person always lands on the welcome screen and a signed-in one never does,
 * and nothing reads the answer any more.
 *
 * What is left is what `features/discover/__tests__/coverage.test.ts` does
 * not already cover. That file owns the welcome sheet's joins — that every
 * id has a picture, that the ids and angles are distinct, that no card runs
 * off the stage sideways — and this one owns the properties it does not: how
 * many people are in the sheet, that they land one after another, that none
 * of them runs off the bottom, and that the pile is stacked the way round
 * that keeps all twelve faces visible.
 */

import { AspectRatio } from '@/constants/theme';
import { WELCOME_SHEET, WELCOME_STAGE } from '@/features/onboarding/welcome';

type Frame = (typeof WELCOME_SHEET)[number];

/** A card's height, in the same percent-of-stage units as its `y`. */
const heightOf = (frame: Frame) => (frame.w / AspectRatio.editorial) * WELCOME_STAGE;

/**
 * The part of a print that must never be covered.
 *
 * Every cover is a full-length photograph on a plain ground, so the person's
 * head sits in the top fifth and across the middle of the frame. Overlap
 * anywhere else is the arrangement working; overlap here is a decapitated
 * card, which is what the first version of this pile did to four of them.
 */
const faceOf = (frame: Frame) => ({
  left: frame.x + frame.w * 0.3,
  right: frame.x + frame.w * 0.7,
  top: frame.y,
  bottom: frame.y + heightOf(frame) * 0.22,
});

/** The four rows of the pile, by the y bands the sheet is authored in. */
const ROWS = [
  WELCOME_SHEET.filter((frame) => frame.y < 15),
  WELCOME_SHEET.filter((frame) => frame.y >= 15 && frame.y < 38),
  WELCOME_SHEET.filter((frame) => frame.y >= 38 && frame.y < 60),
  WELCOME_SHEET.filter((frame) => frame.y >= 60),
];

describe('the welcome sheet', () => {
  it('shows twelve people rather than making one the face of the product', () => {
    expect(WELCOME_SHEET).toHaveLength(12);
    expect(new Set(WELCOME_SHEET.map((frame) => frame.id)).size).toBe(12);
  });

  it('centres every row on the same axis', () => {
    // The first composition ran 2-89 across the top and 16-96 along the
    // bottom, so the pile leaned left at the top and right at the bottom
    // under a centred wordmark. That reads as a layout bug, and it is the
    // kind of thing nobody re-measures by hand after editing a sheet.
    for (const row of ROWS) {
      expect(row).toHaveLength(3);
      const left = Math.min(...row.map((frame) => frame.x));
      const right = Math.max(...row.map((frame) => frame.x + frame.w));
      expect((left + right) / 2).toBe(50);
    }
  });

  it('lands the cards one after another', () => {
    const delays = WELCOME_SHEET.map((frame) => frame.delay);
    // Ascending and distinct: a shared delay is two cards landing on the same
    // frame, which is a flash rather than a sequence.
    expect([...delays].sort((a, b) => a - b)).toEqual(delays);
    expect(new Set(delays).size).toBe(delays.length);
  });

  it('never lets a nearer print cover the face of one behind it', () => {
    // The property the first version of this pile got backwards. A card in
    // front has to lie *lower*, because these are full-length photographs
    // and a nearer print sitting higher lands squarely on the head of the
    // one behind it.
    //
    // Checked pair by pair against the face box rather than by comparing
    // rows, so the small vertical jitter that stops the rows reading as a
    // grid stays legal and a genuine collision still fails.
    for (const near of WELCOME_SHEET) {
      for (const far of WELCOME_SHEET) {
        if (near.depth <= far.depth) continue;
        const face = faceOf(far);
        const hits =
          near.x < face.right &&
          near.x + near.w > face.left &&
          near.y < face.bottom &&
          near.y + heightOf(near) > face.top;
        expect(`${near.id} over ${far.id}: ${hits}`).toBe(`${near.id} over ${far.id}: false`);
      }
    }
  });

  it('deals the pile from the back row forwards', () => {
    // The build has to run away-to-near, or a card flips into place behind
    // ones that are already down and the deal reads as a glitch. Compared
    // row against row rather than card against card: within a row the depths
    // differ by a hair, only to settle which of two rotated corners wins.
    for (let i = 1; i < ROWS.length; i += 1) {
      const behind = ROWS[i - 1];
      const infront = ROWS[i];
      expect(Math.max(...behind.map((frame) => frame.delay))).toBeLessThan(
        Math.min(...infront.map((frame) => frame.delay)),
      );
      expect(Math.max(...behind.map((frame) => frame.depth))).toBeLessThan(
        Math.min(...infront.map((frame) => frame.depth)),
      );
    }
  });

  it('keeps every print inside the stage it is placed on', () => {
    // A card is placed by its top-left corner, so a row authored low enough
    // runs off the bottom — where nothing clips it. It slides under the Get
    // started button instead. One percent of slack for the rotations.
    for (const frame of WELCOME_SHEET) {
      expect(frame.y + heightOf(frame)).toBeLessThanOrEqual(101);
      expect(frame.depth).toBeGreaterThanOrEqual(0);
      expect(frame.depth).toBeLessThanOrEqual(1);
    }
  });
});
