import { AspectRatio } from '@/constants/theme';

/**
 * Which height a tile takes in the masonry grid.
 *
 * A board reads as a board because the tiles do not line up. Every reference
 * board app varies tile height, and the reason is structural rather than
 * decorative: a grid of identical rectangles is scanned row by row, and a
 * staggered one is scanned as a surface, which is how somebody browses
 * clothes rather than reads a list.
 *
 * **Derived from the id, not random.** A random height per render reflows the
 * whole board on every scroll and gives somebody a different layout each time
 * they open the app, which reads as instability rather than variety. Hashing
 * the id means a collection sits at the same height forever.
 *
 * **Only two steps, and both tall.** The covers are generated at 2:3, so
 * `tall` is the uncropped picture and `editorial` (3:4) trims about an eighth
 * from the centre — which on a full-length figure takes floor and ceiling
 * rather than head and feet. A wider step would start cutting people, and a
 * landscape tile in a fashion board looks like a mistake.
 */
export function tileRatio(id: string): number {
  let hash = 0;
  for (let index = 0; index < id.length; index += 1) {
    // djb2, enough for a stable two-way split and small enough to read.
    hash = (hash * 33 + id.charCodeAt(index)) % 100_000;
  }
  return hash % 2 === 0 ? AspectRatio.tall : AspectRatio.editorial;
}
