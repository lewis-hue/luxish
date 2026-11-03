import { blurhashFor } from './blurhashes';
import type { InspirationAsset, SourceRecord } from './types';

/**
 * Cover imagery for the style taxonomy.
 *
 * Generated with `muse-image-1.0` rather than licensed, because every free stock
 * source that would fit prohibits exactly this app shape — Unsplash and Pexels both
 * forbid an app whose content *is* their library, and Unsplash additionally mandates
 * hotlinking as a material-breach term, which rules out serving a CDN derivative.
 * Generated imagery we own outright: no attribution obligation, no re-hosting
 * restriction, no takedown propagation to build. See
 * `docs/architecture/image-sourcing.md`, and `scripts/generate_style_imagery.py` for
 * the prompts.
 *
 * Bundled as static assets rather than fetched: Discover is the first screen, and a
 * first paint that waits on twelve network images is the difference between an app
 * that feels fast and one that does not.
 *
 * Every asset here carries `isGenerated: true`, which renders the AI-generated
 * disclosure badge that Google Play policy requires.
 */

 
// `require` of a bundled asset resolves to an opaque numeric handle.
const COVERS: Record<string, number> = {
  couples: require('@/assets/images/styles/couples.webp'),
  capsule: require('@/assets/images/styles/capsule.webp'),
  'office-siren': require('@/assets/images/styles/office-siren.webp'),
  festival: require('@/assets/images/styles/festival.webp'),
  'wedding-guest': require('@/assets/images/styles/wedding-guest.webp'),
  y2k: require('@/assets/images/styles/y2k.webp'),
  blokecore: require('@/assets/images/styles/blokecore.webp'),
  gorpcore: require('@/assets/images/styles/gorpcore.webp'),
  'dark-academia': require('@/assets/images/styles/dark-academia.webp'),
  'downtown-romantic': require('@/assets/images/styles/downtown-romantic.webp'),
  'clean-girl': require('@/assets/images/styles/clean-girl.webp'),
  'quiet-luxury': require('@/assets/images/styles/quiet-luxury.webp'),
  streetwear: require('@/assets/images/styles/streetwear.webp'),
  office: require('@/assets/images/styles/office.webp'),
  evening: require('@/assets/images/styles/evening.webp'),
  athleisure: require('@/assets/images/styles/athleisure.webp'),
  minimalist: require('@/assets/images/styles/minimalist.webp'),
  modest: require('@/assets/images/styles/modest.webp'),
  heritage: require('@/assets/images/styles/heritage.webp'),
  tailoring: require('@/assets/images/styles/tailoring.webp'),
  denim: require('@/assets/images/styles/denim.webp'),
  monochrome: require('@/assets/images/styles/monochrome.webp'),
  'date-night': require('@/assets/images/styles/date-night.webp'),
  travel: require('@/assets/images/styles/travel.webp'),
  layering: require('@/assets/images/styles/layering.webp'),
  utility: require('@/assets/images/styles/utility.webp'),
  colour: require('@/assets/images/styles/colour.webp'),
  coquette: require('@/assets/images/styles/coquette.webp'),
  balletcore: require('@/assets/images/styles/balletcore.webp'),
  'mob-wife': require('@/assets/images/styles/mob-wife.webp'),
  techwear: require('@/assets/images/styles/techwear.webp'),
  skater: require('@/assets/images/styles/skater.webp'),
  grunge: require('@/assets/images/styles/grunge.webp'),
  'smart-casual': require('@/assets/images/styles/smart-casual.webp'),
  'elevated-basics': require('@/assets/images/styles/elevated-basics.webp'),
};


/**
 * Small copies, for the places that draw a cover small.
 *
 * A Discover tile is about 114 points wide and a collage card about 100 —
 * roughly 340 pixels on a 3x phone, against masters of 1120 to 1280. Every
 * grid in the app was fetching four times the pixels it could show, which on
 * the welcome screen alone was a megabyte.
 *
 * Made by `scripts/make_thumbnails.py`. Only the look-detail hero and the
 * featured tile read the master.
 */
const THUMBS: Record<string, number> = {
  couples: require('@/assets/images/styles/thumbs/couples.webp'),
  capsule: require('@/assets/images/styles/thumbs/capsule.webp'),
  'office-siren': require('@/assets/images/styles/thumbs/office-siren.webp'),
  festival: require('@/assets/images/styles/thumbs/festival.webp'),
  'wedding-guest': require('@/assets/images/styles/thumbs/wedding-guest.webp'),
  y2k: require('@/assets/images/styles/thumbs/y2k.webp'),
  blokecore: require('@/assets/images/styles/thumbs/blokecore.webp'),
  gorpcore: require('@/assets/images/styles/thumbs/gorpcore.webp'),
  'dark-academia': require('@/assets/images/styles/thumbs/dark-academia.webp'),
  'downtown-romantic': require('@/assets/images/styles/thumbs/downtown-romantic.webp'),
  'clean-girl': require('@/assets/images/styles/thumbs/clean-girl.webp'),
  'quiet-luxury': require('@/assets/images/styles/thumbs/quiet-luxury.webp'),
  streetwear: require('@/assets/images/styles/thumbs/streetwear.webp'),
  office: require('@/assets/images/styles/thumbs/office.webp'),
  evening: require('@/assets/images/styles/thumbs/evening.webp'),
  athleisure: require('@/assets/images/styles/thumbs/athleisure.webp'),
  minimalist: require('@/assets/images/styles/thumbs/minimalist.webp'),
  modest: require('@/assets/images/styles/thumbs/modest.webp'),
  heritage: require('@/assets/images/styles/thumbs/heritage.webp'),
  tailoring: require('@/assets/images/styles/thumbs/tailoring.webp'),
  denim: require('@/assets/images/styles/thumbs/denim.webp'),
  monochrome: require('@/assets/images/styles/thumbs/monochrome.webp'),
  'date-night': require('@/assets/images/styles/thumbs/date-night.webp'),
  travel: require('@/assets/images/styles/thumbs/travel.webp'),
  layering: require('@/assets/images/styles/thumbs/layering.webp'),
  utility: require('@/assets/images/styles/thumbs/utility.webp'),
  colour: require('@/assets/images/styles/thumbs/colour.webp'),
  coquette: require('@/assets/images/styles/thumbs/coquette.webp'),
  balletcore: require('@/assets/images/styles/thumbs/balletcore.webp'),
  'mob-wife': require('@/assets/images/styles/thumbs/mob-wife.webp'),
  techwear: require('@/assets/images/styles/thumbs/techwear.webp'),
  skater: require('@/assets/images/styles/thumbs/skater.webp'),
  grunge: require('@/assets/images/styles/thumbs/grunge.webp'),
  'smart-casual': require('@/assets/images/styles/thumbs/smart-casual.webp'),
  'elevated-basics': require('@/assets/images/styles/thumbs/elevated-basics.webp'),
};

/** Shared provenance: we generated these, so we hold the rights. */
function generatedSource(categoryId: string): SourceRecord {
  return {
    provider: 'generated',
    providerId: `muse-image-1.0/${categoryId}`,
    sourceUrl: 'https://dev.meta.ai/docs/image-generation',
    creatorName: null,
    creatorUrl: null,
    license: 'owned-generated',
    retrievedAt: '2026-10-27',
    // We own it, so no credit is owed — but the AI badge is still shown.
    attributionRequired: false,
    hotlinkOnly: false,
  };
}

export function coverFor(categoryId: string, alt: string): InspirationAsset | null {
  const source = COVERS[categoryId];
  if (!source) return null;
  return {
    id: `cover-${categoryId}`,
    // Static assets resolve through `require`, so there is no URI to carry.
    uri: '',
    localSource: source,
    // Preferred by anything drawing this small. Null for a cover with no
    // thumbnail yet, and callers fall back to the master rather than
    // rendering nothing.
    thumbSource: THUMBS[categoryId] ?? null,
    // Rendered instantly while the full image decodes, so the grid never shows
    // empty rectangles on first paint.
    blurhash: blurhashFor(`styles/${categoryId}`),
    width: 768,
    height: 1024,
    source: generatedSource(categoryId),
    alt,
    isGenerated: true,
  };
}

export function hasCover(categoryId: string): boolean {
  return categoryId in COVERS;
}


/**
 * The second and third picture of each collection.
 *
 * A collection is an aesthetic, not an outfit, and one photograph of one
 * person cannot carry that — it says "this is what a gorpcore person looks
 * like" when the honest claim is "here is one of them". These are the same
 * clothes on different people: different ages, builds and skin tones, cast
 * deliberately to fill the gaps the first set left.
 *
 * `require` needs a literal path, so this table is generated rather than
 * looked up: Metro resolves bundled assets at build time and a computed path
 * resolves to nothing at all.
 */
/**
 * One extra picture of the same collection, keyed by the number in its file
 * name. The number is carried rather than inferred from position: a deleted
 * picture used to renumber the one after it, which silently paired a cover
 * with another picture's blurhash.
 */
type Variant = { readonly n: number; readonly source: number };

const VARIANTS: Record<string, readonly Variant[]> = {
  couples: [
    { n: 2, source: require('@/assets/images/styles/couples-2.webp') },
    { n: 3, source: require('@/assets/images/styles/couples-3.webp') },
  ],
  capsule: [
    { n: 2, source: require('@/assets/images/styles/capsule-2.webp') },
    { n: 3, source: require('@/assets/images/styles/capsule-3.webp') },
  ],
  'office-siren': [
    { n: 2, source: require('@/assets/images/styles/office-siren-2.webp') },
    { n: 3, source: require('@/assets/images/styles/office-siren-3.webp') },
  ],
  festival: [
    { n: 2, source: require('@/assets/images/styles/festival-2.webp') },
    { n: 3, source: require('@/assets/images/styles/festival-3.webp') },
  ],
  'wedding-guest': [
    { n: 2, source: require('@/assets/images/styles/wedding-guest-2.webp') },
    { n: 3, source: require('@/assets/images/styles/wedding-guest-3.webp') },
  ],
  y2k: [
    { n: 2, source: require('@/assets/images/styles/y2k-2.webp') },
    { n: 3, source: require('@/assets/images/styles/y2k-3.webp') },
  ],
  blokecore: [
    { n: 2, source: require('@/assets/images/styles/blokecore-2.webp') },
    { n: 3, source: require('@/assets/images/styles/blokecore-3.webp') },
  ],
  gorpcore: [
    { n: 2, source: require('@/assets/images/styles/gorpcore-2.webp') },
    { n: 3, source: require('@/assets/images/styles/gorpcore-3.webp') },
  ],
  'dark-academia': [
    { n: 2, source: require('@/assets/images/styles/dark-academia-2.webp') },
    { n: 3, source: require('@/assets/images/styles/dark-academia-3.webp') },
  ],
  'downtown-romantic': [
    { n: 2, source: require('@/assets/images/styles/downtown-romantic-2.webp') },
    { n: 3, source: require('@/assets/images/styles/downtown-romantic-3.webp') },
  ],
  'clean-girl': [
    { n: 2, source: require('@/assets/images/styles/clean-girl-2.webp') },
    { n: 3, source: require('@/assets/images/styles/clean-girl-3.webp') },
  ],
  'quiet-luxury': [
    { n: 2, source: require('@/assets/images/styles/quiet-luxury-2.webp') },
    { n: 3, source: require('@/assets/images/styles/quiet-luxury-3.webp') },
  ],
  streetwear: [
    { n: 2, source: require('@/assets/images/styles/streetwear-2.webp') },
    { n: 3, source: require('@/assets/images/styles/streetwear-3.webp') },
  ],
  office: [
    { n: 2, source: require('@/assets/images/styles/office-2.webp') },
    { n: 3, source: require('@/assets/images/styles/office-3.webp') },
  ],
  evening: [
    { n: 2, source: require('@/assets/images/styles/evening-2.webp') },
    { n: 3, source: require('@/assets/images/styles/evening-3.webp') },
  ],
  athleisure: [
    { n: 2, source: require('@/assets/images/styles/athleisure-2.webp') },
    { n: 3, source: require('@/assets/images/styles/athleisure-3.webp') },
  ],
  minimalist: [
    { n: 2, source: require('@/assets/images/styles/minimalist-2.webp') },
    { n: 3, source: require('@/assets/images/styles/minimalist-3.webp') },
  ],
  modest: [
    { n: 2, source: require('@/assets/images/styles/modest-2.webp') },
    { n: 3, source: require('@/assets/images/styles/modest-3.webp') },
  ],
  heritage: [
    { n: 2, source: require('@/assets/images/styles/heritage-2.webp') },
    { n: 3, source: require('@/assets/images/styles/heritage-3.webp') },
  ],
  tailoring: [
    { n: 2, source: require('@/assets/images/styles/tailoring-2.webp') },
    { n: 3, source: require('@/assets/images/styles/tailoring-3.webp') },
  ],
  denim: [
    { n: 2, source: require('@/assets/images/styles/denim-2.webp') },
    { n: 3, source: require('@/assets/images/styles/denim-3.webp') },
  ],
  monochrome: [
    { n: 2, source: require('@/assets/images/styles/monochrome-2.webp') },
    { n: 3, source: require('@/assets/images/styles/monochrome-3.webp') },
  ],
  'date-night': [
    { n: 2, source: require('@/assets/images/styles/date-night-2.webp') },
    { n: 3, source: require('@/assets/images/styles/date-night-3.webp') },
  ],
  travel: [
    { n: 2, source: require('@/assets/images/styles/travel-2.webp') },
    { n: 3, source: require('@/assets/images/styles/travel-3.webp') },
  ],
  layering: [
    { n: 2, source: require('@/assets/images/styles/layering-2.webp') },
    { n: 3, source: require('@/assets/images/styles/layering-3.webp') },
  ],
  utility: [
    { n: 2, source: require('@/assets/images/styles/utility-2.webp') },
    { n: 3, source: require('@/assets/images/styles/utility-3.webp') },
  ],
  colour: [
    { n: 2, source: require('@/assets/images/styles/colour-2.webp') },
    { n: 3, source: require('@/assets/images/styles/colour-3.webp') },
  ],
  coquette: [
    { n: 2, source: require('@/assets/images/styles/coquette-2.webp') },
    { n: 3, source: require('@/assets/images/styles/coquette-3.webp') },
  ],
  balletcore: [
    { n: 2, source: require('@/assets/images/styles/balletcore-2.webp') },
    { n: 3, source: require('@/assets/images/styles/balletcore-3.webp') },
  ],
  'mob-wife': [
    { n: 2, source: require('@/assets/images/styles/mob-wife-2.webp') },
    { n: 3, source: require('@/assets/images/styles/mob-wife-3.webp') },
  ],
  techwear: [
    { n: 2, source: require('@/assets/images/styles/techwear-2.webp') },
    { n: 3, source: require('@/assets/images/styles/techwear-3.webp') },
  ],
  skater: [
    { n: 2, source: require('@/assets/images/styles/skater-2.webp') },
    { n: 3, source: require('@/assets/images/styles/skater-3.webp') },
  ],
  grunge: [
    { n: 2, source: require('@/assets/images/styles/grunge-2.webp') },
    { n: 3, source: require('@/assets/images/styles/grunge-3.webp') },
  ],
  'smart-casual': [
    { n: 2, source: require('@/assets/images/styles/smart-casual-2.webp') },
    { n: 3, source: require('@/assets/images/styles/smart-casual-3.webp') },
  ],
  'elevated-basics': [
    { n: 2, source: require('@/assets/images/styles/elevated-basics-2.webp') },
    { n: 3, source: require('@/assets/images/styles/elevated-basics-3.webp') },
  ],
};

/**
 * Every picture of one collection, cover first.
 *
 * Callers that want a single image still use `coverFor`. This is for the
 * places that can show more than one without repeating a collection: the
 * browse grid, and a gallery on the collection itself.
 */
export function picturesFor(
  categoryId: string,
  alt: string,
): readonly InspirationAsset[] {
  const cover = coverFor(categoryId, alt);
  if (!cover) return [];
  const extra = (VARIANTS[categoryId] ?? []).map(({ n, source }) => ({
    ...cover,
    // Distinct ids: these end up as list keys, and two tiles sharing one is
    // a recycled row showing the wrong picture.
    id: `cover-${categoryId}-${n}`,
    localSource: source,
    // Preferred by anything drawing this small. Null for a cover with no
    // thumbnail yet, and callers fall back to the master rather than
    // rendering nothing.
    thumbSource: THUMBS[categoryId] ?? null,
    blurhash: blurhashFor(`styles/${categoryId}-${n}`),
  }));
  return [cover, ...extra];
}

/** How many pictures a collection has. */
export function pictureCount(categoryId: string): number {
  return hasCover(categoryId) ? 1 + (VARIANTS[categoryId]?.length ?? 0) : 0;
}
