/**
 * The arithmetic of pinching a picture, kept out of the component.
 *
 * All of it runs on the UI thread inside worklets, where a mistake
 * is invisible until somebody's finger finds it. Pulling the sums
 * out here makes them ordinary functions with ordinary tests.
 */

/** As far in as a pinch will go. Past this it is pixels, not detail. */
export const MOST_ZOOM = 4;

/**
 * Where the surrounding page has finished dissolving.
 *
 * The fade runs over the first part of the zoom rather than all of
 * it: by the time somebody is at twice the size they are looking at
 * the picture and nothing else, and carrying the grid underneath to
 * four times would mean it was still faintly there throughout.
 */
export const FADED_BY = 1.6;

export function clampZoom(scale: number): number {
  'worklet';
  if (!Number.isFinite(scale)) return 1;
  return Math.min(MOST_ZOOM, Math.max(1, scale));
}

/**
 * How far the picture may be pushed from centre at this scale.
 *
 * **Half the overflow, because the picture is centred.** Zooming to
 * 2x on a 400pt-wide frame makes an 800pt picture whose edges sit
 * 200pt beyond each side, so that is exactly how far it can travel
 * before a gap appears. At 1x there is no overflow and no panning:
 * a picture that can be dragged off its own frame reads as broken.
 */
export function panLimit(frame: number, scale: number): number {
  'worklet';
  if (!Number.isFinite(frame) || !Number.isFinite(scale)) return 0;
  return Math.max(0, (frame * scale - frame) / 2);
}

/** Held inside the frame, so no edge can be dragged into view. */
export function clampPan(offset: number, frame: number, scale: number): number {
  'worklet';
  const limit = panLimit(frame, scale);
  if (!Number.isFinite(offset)) return 0;
  return Math.min(limit, Math.max(-limit, offset));
}

/**
 * How visible the page behind the picture should be.
 *
 * 1 while nothing is zoomed, 0 once the picture has taken over.
 * Linear between: a curve here would either hold the grid on screen
 * too long or snatch it away on the first millimetre of a pinch.
 */
export function surroundOpacity(scale: number): number {
  'worklet';
  if (!Number.isFinite(scale) || scale <= 1) return 1;
  if (scale >= FADED_BY) return 0;
  return 1 - (scale - 1) / (FADED_BY - 1);
}

/** Whether a pinch has actually begun, as opposed to a resting hand. */
export function isZoomed(scale: number): boolean {
  'worklet';
  // A hair over 1, because a pinch that ends at 1.0001 should still
  // give the page back its scrolling.
  return Number.isFinite(scale) && scale > 1.01;
}
