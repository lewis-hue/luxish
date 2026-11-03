import type { CollageFrame } from '@/components/ui/collage';

/**
 * The pile of prints an empty screen opens on.
 *
 * A screen with nothing on it yet is still a screen somebody is looking at,
 * and a line of grey text in the middle of it says the app has nothing to
 * offer. These say what the screen is *for* by showing it: three prints at
 * angles, which is what the thing looks like once it has something in it.
 *
 * **Only for `empty`.** An error, an offline state or a feature that is not
 * built yet must stay plain — decorating a failure is how a broken screen
 * gets mistaken for a working one, and the brief requires that a capability
 * never misrepresent its readiness.
 *
 * Each sheet is cast for its screen: the boards sheet is the kind of thing
 * people pin, the plan sheet is a week of occasions. Fixed rather than
 * sampled per launch, for the same reason the welcome sheet is — a screen
 * that looks different every time reads as unfinished.
 *
 * **Picked by cast and by aesthetic**, on the rule `WELCOME_SHEET` sets out
 * at length: no sheet repeats a region across its three cards, and the
 * aesthetics belong to the audience this is for rather than being whichever
 * pictures sat together nicely. Check both tables before swapping an id.
 *
 * The stage is shallow (see `EMPTY_STAGE`) because this sits above a heading
 * rather than filling a screen, and the cards are smaller and tighter than
 * the welcome sheet's for the same reason.
 */

/** Width-to-height of the empty-state stage. Shallow: it has a heading under it. */
export const EMPTY_STAGE = 1.55;

export const BOARDS_SHEET: readonly CollageFrame[] = [
  { id: 'downtown-romantic', alt: 'A downtown romantic look', x: 12, y: 16, w: 30, rotate: -8, delay: 0 },
  { id: 'y2k', alt: 'A Y2K look', x: 35, y: 2, w: 30, rotate: 4, delay: 110 },
  { id: 'gorpcore', alt: 'A gorpcore look', x: 58, y: 18, w: 30, rotate: 9, delay: 220 },
];

export const SAVED_SHEET: readonly CollageFrame[] = [
  { id: 'streetwear', alt: 'A streetwear look', x: 12, y: 18, w: 30, rotate: 7, delay: 0 },
  { id: 'office-siren', alt: 'An office siren look', x: 35, y: 2, w: 30, rotate: -5, delay: 110 },
  { id: 'modest', alt: 'A modest look', x: 58, y: 16, w: 30, rotate: -9, delay: 220 },
];

export const PLAN_SHEET: readonly CollageFrame[] = [
  { id: 'date-night', alt: 'A date night look', x: 12, y: 16, w: 30, rotate: -6, delay: 0 },
  { id: 'wedding-guest', alt: 'A wedding guest look', x: 35, y: 2, w: 30, rotate: 8, delay: 110 },
  { id: 'festival', alt: 'A festival look', x: 58, y: 18, w: 30, rotate: -4, delay: 220 },
];

export const WARDROBE_SHEET: readonly CollageFrame[] = [
  { id: 'clean-girl', alt: 'A clean, minimal look', x: 12, y: 17, w: 30, rotate: 5, delay: 0 },
  { id: 'blokecore', alt: 'A blokecore look', x: 35, y: 2, w: 30, rotate: -7, delay: 110 },
  { id: 'athleisure', alt: 'An athleisure look', x: 58, y: 17, w: 30, rotate: 10, delay: 220 },
];
