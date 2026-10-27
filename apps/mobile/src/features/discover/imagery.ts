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
  streetwear: require('@/assets/images/styles/streetwear.webp'),
  casual: require('@/assets/images/styles/casual.webp'),
  'smart-casual': require('@/assets/images/styles/smart-casual.webp'),
  office: require('@/assets/images/styles/office.webp'),
  formal: require('@/assets/images/styles/formal.webp'),
  evening: require('@/assets/images/styles/evening.webp'),
  athleisure: require('@/assets/images/styles/athleisure.webp'),
  minimalist: require('@/assets/images/styles/minimalist.webp'),
  'warm-weather': require('@/assets/images/styles/warm-weather.webp'),
  'rainy-season': require('@/assets/images/styles/rainy-season.webp'),
  modest: require('@/assets/images/styles/modest.webp'),
  heritage: require('@/assets/images/styles/heritage.webp'),
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
