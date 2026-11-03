/**
 * Pinching a picture, as arithmetic.
 *
 * All of this runs on the UI thread inside worklets, where a mistake
 * is invisible until somebody's finger finds it.
 */
import {
  FADED_BY,
  MOST_ZOOM,
  clampPan,
  clampZoom,
  isZoomed,
  panLimit,
  surroundOpacity,
} from '@/features/feed/zoom';

describe('clampZoom', () => {
  it('never shrinks a picture below its frame', () => {
    // Pinching outwards past the fit would leave the frame showing
    // around a picture that is supposed to fill it.
    expect(clampZoom(0.3)).toBe(1);
    expect(clampZoom(1)).toBe(1);
  });

  it('stops where detail does', () => {
    expect(clampZoom(99)).toBe(MOST_ZOOM);
  });

  it('passes an ordinary pinch straight through', () => {
    expect(clampZoom(2.4)).toBe(2.4);
  });

  it('falls back to the fit for a value that is not a number', () => {
    // Both reset rather than clamping to the far end. A gesture that
    // produced NaN and left the picture at maximum zoom would be a
    // screenful of pixels somebody has to pinch their way out of; at
    // the fit they are simply back where they started.
    expect(clampZoom(Number.NaN)).toBe(1);
    expect(clampZoom(Number.POSITIVE_INFINITY)).toBe(1);
  });
});

describe('panLimit', () => {
  it('is nothing at all when the picture fits', () => {
    // A picture that can be dragged off its own frame reads as broken.
    expect(panLimit(400, 1)).toBe(0);
  });

  it('is half the overflow, because the picture is centred', () => {
    // 2x on a 400pt frame is an 800pt picture: 200pt past each side.
    expect(panLimit(400, 2)).toBe(200);
  });

  it('never goes negative on a pinch below the fit', () => {
    expect(panLimit(400, 0.5)).toBe(0);
  });
});

describe('clampPan', () => {
  it('holds the picture inside its frame', () => {
    expect(clampPan(9999, 400, 2)).toBe(200);
    expect(clampPan(-9999, 400, 2)).toBe(-200);
  });

  it('allows nothing while the picture fits', () => {
    expect(clampPan(50, 400, 1)).toBe(0);
  });

  it('leaves a legitimate drag alone', () => {
    expect(clampPan(120, 400, 2)).toBe(120);
  });
});

describe('surroundOpacity', () => {
  it('shows the page in full while nothing is zoomed', () => {
    expect(surroundOpacity(1)).toBe(1);
    expect(surroundOpacity(0.8)).toBe(1);
  });

  it('has finished dissolving well before the zoom has', () => {
    // By twice the size somebody is looking at the picture and
    // nothing else; carrying the grid to 4x would leave it faintly
    // there throughout.
    expect(surroundOpacity(FADED_BY)).toBe(0);
    expect(surroundOpacity(MOST_ZOOM)).toBe(0);
    expect(FADED_BY).toBeLessThan(MOST_ZOOM);
  });

  it('fades through the middle rather than snapping', () => {
    const half = surroundOpacity(1 + (FADED_BY - 1) / 2);
    expect(half).toBeGreaterThan(0.4);
    expect(half).toBeLessThan(0.6);
  });

  it('never leaves the page part-visible on a bad number', () => {
    expect(surroundOpacity(Number.NaN)).toBe(1);
  });
});

describe('isZoomed', () => {
  it('is false at rest, so the page keeps its scrolling', () => {
    expect(isZoomed(1)).toBe(false);
  });

  it('tolerates a pinch that ended a hair above rest', () => {
    // Otherwise a page could be left unable to scroll after a pinch
    // that looked, to the person who made it, like nothing at all.
    expect(isZoomed(1.001)).toBe(false);
  });

  it('is true once somebody is actually in', () => {
    expect(isZoomed(1.5)).toBe(true);
  });
});
