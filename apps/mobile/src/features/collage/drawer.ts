/**
 * Where the picture drawer comes to rest.
 *
 * **Why this is a module and not four lines in a gesture callback.**
 * It was four lines in a gesture callback, and that is untestable: a
 * worklet body only runs under a real touch on a real device, so the
 * one thing anybody could say about this drawer was that it compiled.
 * The same move was made for pinch-zoom (`feed/zoom.ts`) and for the
 * tab bar's reading of attention (`navigation/attention.ts`) for the
 * same reason - the gesture is the part a machine cannot check, so
 * everything that is a *decision* is lifted out of it and left here,
 * where it can be.
 *
 * Two stops, not free movement: `0` is showing the pictures and
 * `peek` is out of the way. A drawer parked at an arbitrary height is
 * one somebody has to keep adjusting, and the complaint that started
 * this work was the opposite failure - a handle that said it could be
 * pulled and could not, so the lower half of a collage could not be
 * seen while adding to it.
 *
 * Every function here is a worklet, because the gesture calls them on
 * the UI thread.
 */

/** A flick is a throw, not a drag. Points per second. */
export const FLICK = 500;

/**
 * How far the drawer may be pulled, from the screen's height.
 *
 * Far enough that only the handle and the search box are left, so
 * what is uncovered is most of the canvas rather than a strip of it.
 */
export const PEEK_FRACTION = 0.42;

/** The travel available on a screen of this height. */
export function peekFor(screenHeight: number): number {
  'worklet';
  if (!Number.isFinite(screenHeight) || screenHeight <= 0) return 0;
  return Math.round(screenHeight * PEEK_FRACTION);
}

/**
 * Where the drawer sits mid-drag.
 *
 * Bounded at both ends rather than rubber-banded: this is a drawer
 * with two positions, and letting it fly past either would leave it
 * somewhere that is neither. Pulling further than `peek` or pushing
 * above the top does nothing, which is what tells a finger it has
 * reached the end.
 */
export function dragTo(start: number, translation: number, peek: number): number {
  'worklet';
  const wanted = start + translation;
  if (!Number.isFinite(wanted)) return 0;
  return Math.min(peek, Math.max(0, wanted));
}

/**
 * Which stop a released drag goes to.
 *
 * A flick goes the way it was thrown, however far it got - somebody
 * who flicks down from the top means "get out of the way" even though
 * the drawer has barely moved. Anything slower goes to the nearer
 * stop, so a deliberate half-pull resolves rather than hanging.
 */
export function settleTo(at: number, velocity: number, peek: number): number {
  'worklet';
  if (velocity > FLICK) return peek;
  if (velocity < -FLICK) return 0;
  return at > peek / 2 ? peek : 0;
}

/** Whether the drawer is currently covering the canvas. */
export function isShowingPictures(at: number): boolean {
  'worklet';
  return at <= 0;
}
