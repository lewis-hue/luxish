import { type FeedFit } from '@/api/queries/discover-feed';

/**
 * Deal fits into columns the way a masonry does.
 *
 * **For the grids that are not lists.** A virtualised masonry handles
 * this itself, but the related pins under an opened fit sit inside a
 * scroll view, where a nested list would be wrong. Those were laid out
 * with `flexWrap`, which is a *grid*: every wrapped row is as tall as
 * its tallest tile, so a short one leaves a band of empty white
 * beneath it until the next row starts. That is the gap down the left
 * of the board.
 *
 * Here each column is stacked independently and the next fit goes to
 * whichever column is currently shortest, so the gap between two tiles
 * is always the same and the columns end level.
 *
 * **No measuring.** Every fit already carries `coverRatio` from the
 * server, so the heights are known before a single picture has
 * loaded - which is also why the result does not change as they
 * arrive.
 */

import { clampShape } from '@/features/feed/shape';

export function intoColumns(
  fits: readonly FeedFit[],
  columns = 2,
): FeedFit[][] {
  const lanes: FeedFit[][] = Array.from({ length: columns }, () => []);
  // Height per unit of width, which is all that matters for balance.
  const heights = Array.from({ length: columns }, () => 0);

  for (const fit of fits) {
    // The same clamp the tile applies, so the maths matches the
    // layout. They are one function now because they drifted once.
    const ratio = clampShape(fit.coverRatio);
    const shortest = heights.indexOf(Math.min(...heights));
    lanes[shortest].push(fit);
    heights[shortest] += 1 / ratio;
  }

  return lanes;
}
