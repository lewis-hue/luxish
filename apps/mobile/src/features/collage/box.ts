/**
 * The box a collage is composed in.
 *
 * **Why it is not just two lines in the screen.** It was, and the
 * ratio had drifted: the canvas was 4:5 under a comment claiming that
 * was the app's shape, while the app's shape was `UNKNOWN_SHAPE`. The
 * cost of that drift is invisible until the moment it matters - a
 * collage composed at one ratio and posted into a shell of another is
 * cropped at exactly the edges somebody spent their time arranging.
 *
 * Lifted out, the claim "what you arrange is what gets posted" stops
 * being a comment and becomes something a test can hold the two
 * modules to.
 */

import { Spacing } from '@/constants/theme';
import { UNKNOWN_SHAPE } from '@/features/feed/shape';

/**
 * The canvas for a screen of this width.
 *
 * Inset by one gutter each side, because the canvas is a surface
 * being arranged rather than the page itself - it needs an edge to
 * read as a thing with a boundary, which is what a piece dragged to
 * its corner is dragged to.
 */
export function canvasBox(screenWidth: number): { width: number; height: number } {
  const usable = screenWidth - Spacing.three * 2;
  if (!Number.isFinite(usable) || usable <= 0) return { width: 0, height: 0 };
  return { width: usable, height: usable / UNKNOWN_SHAPE };
}

/** The shape a collage is exported in. Must be a shell shape. */
export function canvasShape(): number {
  return UNKNOWN_SHAPE;
}
