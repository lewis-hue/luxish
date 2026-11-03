/**
 * Reading what somebody is doing, so the bar can get out of the way.
 *
 * **Two postures, not two screens.** The app already decides where
 * the tab bar belongs by asking which screen is open, and that is
 * the wrong unit for a page that is both things in turn. A fit's
 * page opens as one photograph filling the screen - somebody is
 * looking at *this*, and five navigation chips across the bottom are
 * sitting on it. Scroll past the picture and the same page becomes a
 * grid of other fits, which is browsing, and the chips are now the
 * useful thing: they are how you leave.
 *
 * So the posture is read from the scroll position rather than from
 * the route. At the top of a focus surface the bar stands down; once
 * somebody has scrolled into the part of the page that offers other
 * things, it comes back.
 *
 * **Hysteresis, because a boundary without it flickers.** A finger
 * resting near the threshold, or the small bounce at the end of a
 * flick, crosses it repeatedly - and the bar would drop and rise
 * several times a second. Showing and hiding use different marks, so
 * once a decision is made it takes a real movement to undo it.
 */

/**
 * How far past the picture counts as having begun to browse.
 *
 * A fraction of the hero rather than a fixed number of points: the
 * hero is as tall as the photograph in it, so the same number would
 * be most of a wide picture and a sliver of a tall one. Three
 * quarters means the picture is mostly gone before the bar returns.
 */
export const BROWSING_BEGINS_AT = 0.75;

/**
 * The band the decision will not flip inside.
 *
 * In points, not a fraction: it is standing in for a finger's worth
 * of jitter and a scroll view's end-of-flick bounce, neither of
 * which scales with the content.
 */
export const STEADY_BAND = 48;

/**
 * Whether a focus surface should keep the bottom of the screen to itself.
 *
 * `was` is the answer last time, which is what makes the band work:
 * with no memory there is one threshold and it flickers.
 */
export function immersed(input: {
  /** How far down the page somebody has scrolled. */
  offsetY: number;
  /** The height of the thing being focused on - the hero picture. */
  focusHeight: number;
  /** The previous answer, so a decision is not undone by jitter. */
  was: boolean;
}): boolean {
  const { offsetY, focusHeight, was } = input;

  // Nothing to be immersed in. A page with no hero is a browsing
  // page from its first pixel.
  if (!Number.isFinite(focusHeight) || focusHeight <= 0) return false;

  const mark = focusHeight * BROWSING_BEGINS_AT;
  // Browsing starts a little later than it stops, so the two
  // decisions cannot chase each other across one line.
  const reveal = mark + STEADY_BAND / 2;
  const hide = Math.max(0, mark - STEADY_BAND / 2);

  if (was) return offsetY < reveal;
  return offsetY < hide;
}

/**
 * Whether this screen is one somebody focuses on before browsing.
 *
 * **Deliberately short.** Every other screen in the app is a list,
 * a form or a tool, and on all of those the bar is wanted from the
 * first pixel: a board is for browsing, a wardrobe is for finding,
 * and a settings page has nothing to be immersed in. Adding a screen
 * here means claiming it opens on one thing worth the whole screen,
 * which is a strong claim and should stay rare.
 *
 * Matched on the first segment, so `/fit/<id>` is one entry and
 * `/fitting-room` is not it.
 */
const FOCUS_FIRST: ReadonlySet<string> = new Set(['fit']);

export function focusesFirst(pathname: string): boolean {
  const [, head] = pathname.split('/');
  return Boolean(head) && FOCUS_FIRST.has(head);
}
