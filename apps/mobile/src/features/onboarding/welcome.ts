/**
 * The pictures the welcome screen opens on, and where each one sits.
 *
 * **Twelve people, and the collage is now the whole screen.** A drawn figure
 * used to hold six prints over his head, straining under the weight; the
 * sketch is gone and the pile has taken the space it was using. That is why
 * the stage went from landscape to portrait and the sheet from six cards to
 * twelve: there is nothing under it to leave room for any more.
 *
 * **Cast so that no two cards are the same person.** Every entry below is a
 * different (region, gender) pair out of `scripts/generate_style_covers.py`'s
 * casting table — twelve pairs, twelve cards, no repeats:
 *
 *   Black man · Latina woman · white man · East Asian woman · white woman ·
 *   Southeast Asian man · Black woman · Middle Eastern man · East Asian man ·
 *   Middle Eastern woman · South Asian woman · Latino man
 *
 * Eight of the aesthetics are what this audience actually wears (streetwear,
 * y2k, blokecore, balletcore, downtown romantic, skater, dark academia,
 * clean girl) and four are the smart-casual register the same people wear to
 * everything else. Check the casting table before swapping an id: a swap
 * that duplicates a pair quietly narrows who the product appears to be for.
 *
 * This module used to also hold a "has this device seen the introduction"
 * flag, which decided whether the tabs or the welcome screen came up first.
 * It no longer decides anything: every feature is behind sign-in, so a
 * signed-out person always lands here and a signed-in one never does. A
 * stored answer to a question nobody asks is a thing to keep true for no
 * reason, so it went with the branch that read it.
 */
export const WELCOME_SHEET = [
  // Row one, furthest back. Depth is the whole arrangement — see below.
  { id: 'streetwear', alt: 'A streetwear look', x: 0, y: 3, w: 33, rotate: -6, depth: 0, delay: 0 },
  { id: 'y2k', alt: 'A Y2K look', x: 32, y: 1, w: 36, rotate: 4, depth: 0.08, delay: 60 },
  { id: 'blokecore', alt: 'A blokecore look', x: 69, y: 6, w: 31, rotate: -3, depth: 0, delay: 120 },

  { id: 'balletcore', alt: 'A balletcore look', x: 0, y: 26, w: 31, rotate: 7, depth: 0.34, delay: 190 },
  {
    id: 'downtown-romantic',
    alt: 'A downtown romantic look',
    x: 29,
    y: 23,
    w: 38,
    rotate: -5,
    depth: 0.42,
    delay: 250,
  },
  { id: 'skater', alt: 'A skater look', x: 70, y: 28, w: 30, rotate: 6, depth: 0.34, delay: 310 },

  {
    id: 'smart-casual',
    alt: 'A smart casual look',
    x: 0,
    y: 47,
    w: 32,
    rotate: -4,
    depth: 0.67,
    delay: 380,
  },
  {
    id: 'dark-academia',
    alt: 'A dark academia look',
    x: 30,
    y: 44,
    w: 37,
    rotate: 5,
    depth: 0.75,
    delay: 440,
  },
  {
    id: 'monochrome',
    alt: 'An all-black monochrome look',
    x: 68,
    y: 49,
    w: 32,
    rotate: -8,
    depth: 0.67,
    delay: 500,
  },

  // Row four, nearest the eye and last to land.
  { id: 'modest', alt: 'A modest look', x: 0, y: 68, w: 30, rotate: 8, depth: 0.94, delay: 570 },
  {
    id: 'clean-girl',
    alt: 'A clean, minimal look',
    x: 31,
    y: 65,
    w: 37,
    rotate: -7,
    depth: 1,
    delay: 630,
  },
  {
    id: 'athleisure',
    alt: 'An athleisure look',
    x: 69,
    y: 70,
    w: 31,
    rotate: 3,
    depth: 0.94,
    delay: 690,
  },
] as const;

/**
 * The welcome stage, as width over height.
 *
 * Portrait, because the pile is the screen now rather than a thing a sketch
 * was holding up. 0.72 is close to what is actually left on a 390x844 phone
 * once the masthead, the button and the safe areas have taken theirs, so the
 * composition very nearly fills it. The screen measures the box it is given
 * and fits the stage inside *both* dimensions, so on a shorter phone this
 * narrows rather than overflowing.
 *
 * **Both the rows and the whole pile are centred on 50**, which a test pins.
 * The first composition ran 2 to 89 across one row and 16 to 96 across
 * another, and under a centred wordmark that reads as a layout bug rather
 * than as an arrangement. Each of the four rows now spans 0 to 100, with the
 * angles and the small vertical offsets doing the scattering instead of the
 * margins.
 *
 * **Depth rises down the stage, and that is not decoration.** These are
 * full-length photographs: the face is in the top fifth of every card. A
 * pile where the nearer print sits higher therefore covers the face of the
 * one behind it, which was the first version of this and was wrong. Sorting
 * the other way — nearest lowest — means an overlap only ever eats the card
 * behind it from the knees down, so all twelve people stay visible. It also
 * happens to be what a pile of prints looks like from above.
 */
export const WELCOME_STAGE = 0.72;
