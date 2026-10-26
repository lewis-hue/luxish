import type { StyleCollection } from './types';

/**
 * The curated style taxonomy (§1).
 *
 * This is product content, not placeholder data: these are the categories the
 * stylist reasons about, the wardrobe tags against, and Discover browses. The
 * `formality` and `season` values are the same vocabulary the backend stores on a
 * garment, so a collection can be turned into a wardrobe query directly.
 *
 * `cover` is deliberately null for now. No inspiration image source has been
 * licensed and configured yet, and rendering stock photography before its terms are
 * verified is the one mistake here that is expensive to undo. `StyleTile` renders an
 * editorial typographic cover while `cover` is null, so the grid is complete and
 * usable today and gains photography when a source is wired.
 */

/** Matches the backend garment `formality` vocabulary. */
export type Formality = 'casual' | 'smart_casual' | 'business' | 'formal' | 'black_tie';

export type Season = 'warm' | 'cool' | 'transitional' | 'all_year';

export interface StyleCategory extends Omit<StyleCollection, 'cover'> {
  /** Null until an inspiration source is licensed and configured. */
  cover: StyleCollection['cover'] | null;
  formality: Formality;
  seasons: readonly Season[];
  /** Short, concrete garment cues the stylist can anchor on. */
  cues: readonly string[];
}

export const STYLE_CATEGORIES: readonly StyleCategory[] = [
  {
    id: 'streetwear',
    title: 'Streetwear',
    subtitle: 'Relaxed silhouettes, bold layers, statement footwear',
    cover: null,
    lookCount: null,
    formality: 'casual',
    seasons: ['cool', 'transitional'],
    cues: ['oversized outerwear', 'graphic layers', 'sneakers', 'cargo trousers'],
  },
  {
    id: 'casual',
    title: 'Casual',
    subtitle: 'Easy daily pieces that still look considered',
    cover: null,
    lookCount: null,
    formality: 'casual',
    seasons: ['all_year'],
    cues: ['denim', 'knitwear', 'simple tees', 'clean trainers'],
  },
  {
    id: 'smart-casual',
    title: 'Smart casual',
        subtitle: 'The flexible middle ground — tailored but unstuffy',
    cover: null,
    lookCount: null,
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['unstructured blazer', 'chinos', 'loafers', 'fine-gauge knit'],
  },
  {
    id: 'office',
    title: 'Office',
    subtitle: 'Dress-code safe without looking severe',
    cover: null,
    lookCount: null,
    formality: 'business',
    seasons: ['all_year'],
    cues: ['tailored trousers', 'shirting', 'structured bag', 'low heel or derby'],
  },
  {
    id: 'formal',
    title: 'Formal',
    subtitle: 'Full tailoring for occasions that ask for it',
    cover: null,
    lookCount: null,
    formality: 'formal',
    seasons: ['all_year'],
    cues: ['matched suit', 'crisp shirt', 'leather oxfords', 'minimal jewellery'],
  },
  {
    id: 'evening',
    title: 'Evening',
    subtitle: 'Texture, drape and a little shine after dark',
    cover: null,
    lookCount: null,
    formality: 'black_tie',
    seasons: ['all_year'],
    cues: ['satin or velvet', 'occasion dress', 'heeled sandal', 'clutch'],
  },
  {
    id: 'athleisure',
    title: 'Athleisure',
    subtitle: 'Performance pieces styled to leave the house in',
    cover: null,
    lookCount: null,
    formality: 'casual',
    seasons: ['all_year'],
    cues: ['technical outerwear', 'leggings or joggers', 'runners', 'crossbody'],
  },
  {
    id: 'minimalist',
    title: 'Minimalist',
    subtitle: 'Few colours, clean lines, nothing extra',
    cover: null,
    lookCount: null,
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['neutral palette', 'column shapes', 'unbranded leather', 'flat sandal'],
  },
  {
    id: 'warm-weather',
    title: 'Warm weather',
    subtitle: 'Breathable fabrics for heat and humidity',
    cover: null,
    lookCount: null,
    formality: 'casual',
    seasons: ['warm'],
    cues: ['linen', 'open weave', 'light colours', 'sandals'],
  },
  {
    id: 'rainy-season',
    title: 'Rainy season',
    subtitle: 'Staying dry without giving up on the outfit',
    cover: null,
    lookCount: null,
    formality: 'casual',
    seasons: ['transitional'],
    cues: ['water-resistant shell', 'cropped hem', 'closed shoe', 'dark base'],
  },
  {
    id: 'modest',
    title: 'Modest',
    subtitle: 'Fuller coverage, strong on layering and proportion',
    cover: null,
    lookCount: null,
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['long sleeve', 'midi or maxi length', 'high neckline', 'loose cut'],
  },
  {
    id: 'heritage',
    title: 'Heritage & print',
    subtitle: 'Regional textiles and print-led looks',
    cover: null,
    lookCount: null,
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['woven print', 'artisanal detail', 'solid pairing', 'statement accessory'],
  },
] as const;

export function categoryById(id: string): StyleCategory | undefined {
  return STYLE_CATEGORIES.find((c) => c.id === id);
}
