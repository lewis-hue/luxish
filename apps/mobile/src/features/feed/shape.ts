/**
 * The shapes a cover may be shown in, anywhere in the app.
 *
 * **One shell for everything somebody posts.** A picture out of the
 * studio is a different shape from a photograph off a phone - a
 * generated full-length figure came back at about 0.47 where a camera
 * roll photograph sits near 0.6 - and before this the two were shown
 * differently: the tall one narrowed to fit its height budget and sat
 * inset from both edges while everything around it reached them. Same
 * app, same feed, two visibly different cards, and the difference
 * tracked how the picture was made rather than anything about it.
 *
 * So every cover is shown within these bounds. A picture inside them
 * is untouched, which is almost all of them. One outside is shown at
 * the nearest bound and cropped to it.
 */

/** The shape a cover falls back to when the server did not say. */
export const UNKNOWN_SHAPE = 3 / 4;

/**
 * The tallest and widest a cover is ever shown.
 *
 * `tallest` is 9:16 - a whole phone screen turned upright, and the
 * tallest thing any camera or any generator here produces by default.
 * Past it a picture is cropped rather than given a narrower card.
 */
export const SHAPE = { tallest: 9 / 16, widest: 1.45 } as const;

/** This shape, brought inside the bounds every card is drawn in. */
export function clampShape(ratio: number | null | undefined): number {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) {
    return UNKNOWN_SHAPE;
  }
  return Math.min(SHAPE.widest, Math.max(SHAPE.tallest, ratio));
}
