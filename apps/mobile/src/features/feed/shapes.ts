/**
 * The shape of a fit's cover, remembered across screens.
 *
 * **Why a screen needs this before its own request returns.** Opening a
 * pin is a navigation, and the detail endpoint is a round trip. The fit
 * screen used to size its frame from a 3:4 guess until that response
 * arrived and then snap to the real ratio - so a photograph somebody had
 * just tapped to look at resized while they were looking at it. The tile
 * they tapped already knew the answer; this is how it reaches the screen
 * that needs it.
 *
 * **Written where every path already passes.** Both the grids and the
 * detail screen build their fits through `toFeedFit`, so recording it
 * there means a shape learned on any screen is known on the next one,
 * with no route parameters to thread and no call site to forget.
 *
 * A plain Map, not state: nothing should re-render when it is written,
 * and a post id addresses one cover whose dimensions do not change. It
 * lasts as long as the process, which is the same lifetime as the image
 * cache it is standing in for.
 */

const shapes = new Map<string, number>();

/** Record a cover's width over height. Ignores a missing or absurd value. */
export function rememberShape(postId: string, ratio: number | null): void {
  if (!postId || ratio === null || !Number.isFinite(ratio) || ratio <= 0) return;
  shapes.set(postId, ratio);
}

/** The cover's shape if any screen has seen it this session. */
export function shapeFor(postId: string): number | undefined {
  return shapes.get(postId);
}

/** Forget everything. For tests, so one case cannot leak into the next. */
export function forgetShapes(): void {
  shapes.clear();
}
