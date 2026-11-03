/**
 * Every card is the same width.
 *
 * **This rule replaced its opposite, deliberately.** The frame used to
 * take the photograph's own shape and narrow itself when a picture was
 * too tall, so that nothing was ever cropped. That kept each picture
 * whole and made the card's width depend on the shape of its contents:
 * a studio render at 0.47 sat visibly inset from both edges while a
 * camera photograph at 0.6 reached them, and the feed looked like two
 * apps depending on how a picture had been made.
 *
 * The product owner's call (2026-11-02) is one shell for everything.
 * So the width is fixed and the height is capped, which means a
 * picture taller than the page is cropped - held down by
 * `SHAPE.tallest`, which only a picture taller than an upright phone
 * screen exceeds, and by the hero opening full screen on tap.
 */

import { heroFrame } from '@/features/feed/hero-frame';
import { SHAPE, clampShape } from '@/features/feed/shape';

/** An iPhone 15 Pro: the width less its 8pt inset each side, and the
 *  height budget a picture is allowed. */
const ACROSS = 393 - 16;
const ROOM = 852 * 0.82;

function shapeOf(frame: { width: number; height: number }): number {
  return Number((frame.width / frame.height).toFixed(4));
}

describe('every card is the same width', () => {
  it.each([
    ['a tall portrait', 0.4623],
    ['the commonest shape here', 0.5625],
    ['a gentler portrait', 0.6667],
    ['a square', 1],
    ['a landscape', 1.5],
  ])('gives %s the full width', (_what, ratio) => {
    // The whole rule. A card that is narrower than its neighbour
    // because of what is inside it is the bug this replaced.
    expect(heroFrame(ratio, ACROSS, ROOM).width).toBe(ACROSS);
  });

  it('never draws one taller than there is room for', () => {
    for (const ratio of [0.3, 0.4623, 0.5625, 1]) {
      expect(heroFrame(ratio, ACROSS, ROOM).height).toBeLessThanOrEqual(ROOM);
    }
  });
});

describe('when the picture fits', () => {
  it('is exactly the picture, uncropped', () => {
    // Almost everything takes this path, and nothing about it changed.
    const frame = heroFrame(0.5625, ACROSS, ROOM);
    expect(frame.cropped).toBe(false);
    expect(shapeOf(frame)).toBeCloseTo(0.5625, 3);
    expect(frame.height).toBeCloseTo(ACROSS / 0.5625, 3);
  });

  it('reports no crop, which is what `cover` then costs here', () => {
    // The hero draws with `cover` unconditionally. Where the frame is
    // the picture's own shape - this case - `cover` and `contain` are
    // the same thing and nothing is lost.
    for (const ratio of [0.5625, 0.6667, 1, 1.5]) {
      expect(heroFrame(ratio, ACROSS, ROOM).cropped).toBe(false);
    }
  });
});

describe('when the picture is taller than the page', () => {
  const tall = heroFrame(0.4, ACROSS, ROOM);

  it('keeps the width and caps the height', () => {
    expect(tall.width).toBe(ACROSS);
    expect(tall.height).toBeCloseTo(ROOM, 3);
  });

  it('reports that it cropped, so nothing letterboxes it', () => {
    // The caller reads this to choose `cover`. Left as `contain`, the
    // picture would sit in a band of grey - which is the complaint
    // the narrowing rule existed to avoid, reintroduced.
    expect(tall.cropped).toBe(true);
  });
});

describe('the clamp in front of it', () => {
  it('keeps a studio render inside the shell', () => {
    // The picture that prompted this: a generated full-length figure
    // came back at about 0.47, well past an upright phone screen.
    expect(clampShape(0.47)).toBeCloseTo(SHAPE.tallest, 4);
  });

  it('leaves an ordinary photograph alone', () => {
    // The one the product owner showed as correct sat near 0.61.
    expect(clampShape(0.61)).toBeCloseTo(0.61, 4);
    expect(clampShape(0.5625)).toBeCloseTo(0.5625, 4);
    expect(clampShape(1)).toBe(1);
  });

  it('caps a very wide picture too', () => {
    expect(clampShape(4)).toBe(SHAPE.widest);
  });

  it('falls back rather than dividing by a shape it was not given', () => {
    // The server sends null when it never measured one.
    for (const bad of [null, undefined, 0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      const got = clampShape(bad as number | null);
      expect(Number.isFinite(got)).toBe(true);
      expect(got).toBeGreaterThan(0);
    }
  });

  it('leaves the height cap unbitten, which is not the same as uncropped', () => {
    // A clamped shape always fits the page on this screen, so
    // `heroFrame` reports no crop. The *picture* is still cropped,
    // by the clamp, before `heroFrame` ever sees it - and reading
    // this flag as "nothing was cropped" is exactly the bug that
    // drew a band of grey down each side of a 0.49 photograph.
    // The hero therefore uses `cover` unconditionally rather than
    // choosing from this.
    for (const ratio of [0.3, 0.47, 0.5625, 0.8, 1, 3]) {
      const frame = heroFrame(clampShape(ratio), ACROSS, ROOM);
      expect(frame.width).toBe(ACROSS);
      expect(frame.cropped).toBe(false);
    }
  });
});

describe('the shapes it must not produce', () => {
  it('returns nothing of zero or negative size', () => {
    for (const ratio of [0.3, 0.4623, 1, 3]) {
      const frame = heroFrame(ratio, ACROSS, ROOM);
      expect(frame.width).toBeGreaterThan(0);
      expect(frame.height).toBeGreaterThan(0);
    }
  });

  it('lives inside a short screen rather than overflowing it', () => {
    // A small phone in landscape, or a split view.
    const cramped = heroFrame(0.5625, ACROSS, 200);
    expect(cramped.height).toBeCloseTo(200, 3);
    expect(cramped.width).toBe(ACROSS);
    expect(cramped.cropped).toBe(true);
  });
});
