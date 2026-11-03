/**
 * The frame a cover is shown in on its own page.
 *
 * **Always the full width.** It did not used to be: a picture too
 * tall for its height budget had the *frame* narrowed to keep the
 * frame and the photograph the same shape, so nothing was ever
 * cropped. That reasoning was sound on its own terms and wrong in
 * aggregate - it made the card's width depend on the shape of what
 * was in it, so a studio render at 0.47 sat visibly inset while a
 * camera photograph at 0.6 reached both edges, and the feed looked
 * like two different apps depending on how a picture had been made.
 *
 * The cost is real and is the one the previous version was avoiding:
 * a picture taller than its budget is cropped, and in a fashion app
 * the bottom of a full-length photograph is the shoes. Two things
 * hold that down. `SHAPE.tallest` is 9:16, so only a picture taller
 * than a whole upright phone screen is touched at all; and the hero
 * opens full-screen on tap, which is one gesture to the whole
 * uncropped picture.
 *
 * Exported for its test: "every card is the same width" is the rule
 * worth pinning, and it is arithmetic.
 */
export function heroFrame(
  ratio: number,
  across: number,
  room: number,
): { width: number; height: number; cropped: boolean } {
  const natural = across / ratio;
  if (natural <= room) return { width: across, height: natural, cropped: false };
  // Too tall for the page. The width is not negotiable, so the
  // height is capped and the picture fills the frame past it.
  return { width: across, height: room, cropped: true };
}
