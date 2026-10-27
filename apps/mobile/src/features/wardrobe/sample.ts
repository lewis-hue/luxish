import { blurhashFor } from '@/features/discover/blurhashes';

/**
 * A sample wardrobe.
 *
 * §3: "Allow a sample wardrobe demonstration before lengthy setup." Someone
 * evaluating the app should see styling work before photographing forty garments,
 * and an empty grid demonstrates nothing.
 *
 * It is labelled as sample everywhere it appears. A demonstration that quietly
 * passes for the user's own data is worse than no demonstration — the moment they
 * add a real garment they cannot tell which is which.
 *
 * The attribute vocabulary deliberately matches the backend's `Garment` model, so
 * these records can be POSTed as real garments when a user chooses to adopt the
 * sample, with no translation layer.
 */

export type Availability = 'available' | 'laundry' | 'unavailable' | 'archived';
export type Formality = 'casual' | 'smart_casual' | 'business' | 'formal' | 'black_tie';

export interface SampleGarment {
  id: string;
  name: string;
  category: string;
  /** Mirrors `Garment.confirmed_attributes` — what a user has stated. */
  confirmed: {
    colour: string;
    formality: Formality;
    seasons: readonly string[];
    material?: string;
  };
  /**
   * Mirrors `Garment.inferred_attributes` with its confidence. Kept separate from
   * confirmed values because a user correction must always win (ADR-010), and the
   * UI shows the difference rather than flattening it.
   */
  inferred?: { pattern?: string; silhouette?: string };
  inferenceConfidence?: number;
  availability: Availability;
  image: number;
  blurhash: string | null;
}

const IMAGES: Record<string, number> = {
  'white-shirt': require('@/assets/images/wardrobe/white-shirt.webp'),
  'navy-blazer': require('@/assets/images/wardrobe/navy-blazer.webp'),
  'cream-trousers': require('@/assets/images/wardrobe/cream-trousers.webp'),
  'indigo-jeans': require('@/assets/images/wardrobe/indigo-jeans.webp'),
  'black-midi-dress': require('@/assets/images/wardrobe/black-midi-dress.webp'),
  'brown-loafers': require('@/assets/images/wardrobe/brown-loafers.webp'),
  'white-trainers': require('@/assets/images/wardrobe/white-trainers.webp'),
  'camel-coat': require('@/assets/images/wardrobe/camel-coat.webp'),
  'linen-shirt': require('@/assets/images/wardrobe/linen-shirt.webp'),
  'striped-knit': require('@/assets/images/wardrobe/striped-knit.webp'),
  'leather-tote': require('@/assets/images/wardrobe/leather-tote.webp'),
  'silk-scarf': require('@/assets/images/wardrobe/silk-scarf.webp'),
};


function item(
  id: string,
  name: string,
  category: string,
  confirmed: SampleGarment['confirmed'],
  options: {
    availability?: Availability;
    inferred?: SampleGarment['inferred'];
    confidence?: number;
  } = {},
): SampleGarment {
  return {
    id: `sample-${id}`,
    name,
    category,
    confirmed,
    inferred: options.inferred,
    inferenceConfidence: options.confidence,
    availability: options.availability ?? 'available',
    image: IMAGES[id],
    blurhash: blurhashFor(`wardrobe/${id}`),
  };
}

export const SAMPLE_WARDROBE: readonly SampleGarment[] = [
  item('white-shirt', 'White poplin shirt', 'shirt', {
    colour: 'white',
    formality: 'business',
    seasons: ['all_year'],
    material: 'cotton',
  }),
  item('navy-blazer', 'Navy wool blazer', 'blazer', {
    colour: 'navy',
    formality: 'business',
    seasons: ['cool', 'transitional'],
    material: 'wool',
  }),
  item('cream-trousers', 'Cream wide-leg trousers', 'trousers', {
    colour: 'cream',
    formality: 'smart_casual',
    seasons: ['warm', 'transitional'],
  }),
  item('indigo-jeans', 'Indigo straight jeans', 'jeans', {
    colour: 'indigo',
    formality: 'casual',
    seasons: ['all_year'],
    material: 'denim',
  }),
  item('black-midi-dress', 'Black crepe midi dress', 'dress', {
    colour: 'black',
    formality: 'formal',
    seasons: ['all_year'],
  }),
  item('brown-loafers', 'Brown penny loafers', 'shoes', {
    colour: 'brown',
    formality: 'smart_casual',
    seasons: ['all_year'],
    material: 'leather',
  }),
  // Deliberately unavailable: the stylist must route around it, and the
  // "garment becomes unavailable" revision demo needs something to exclude.
  item(
    'white-trainers',
    'White leather trainers',
    'shoes',
    { colour: 'white', formality: 'casual', seasons: ['all_year'] },
    { availability: 'laundry' },
  ),
  item('camel-coat', 'Camel wool overcoat', 'coat', {
    colour: 'camel',
    formality: 'smart_casual',
    seasons: ['cool'],
    material: 'wool',
  }),
  item('linen-shirt', 'Sand linen shirt', 'shirt', {
    colour: 'sand',
    formality: 'casual',
    seasons: ['warm'],
    material: 'linen',
  }),
  // Carries a low-confidence inference, so the correction flow has something to
  // correct and the UI can show inferred and confirmed values side by side.
  item(
    'striped-knit',
    'Striped fine knit',
    'knitwear',
    { colour: 'navy', formality: 'casual', seasons: ['cool', 'transitional'] },
    { inferred: { pattern: 'horizontal stripe' }, confidence: 0.42 },
  ),
  item('leather-tote', 'Tan leather tote', 'bag', {
    colour: 'tan',
    formality: 'business',
    seasons: ['all_year'],
    material: 'leather',
  }),
  item('silk-scarf', 'Ochre silk scarf', 'accessory', {
    colour: 'ochre',
    formality: 'smart_casual',
    seasons: ['all_year'],
    material: 'silk',
  }),
];

/** Filters offered above the grid. `all` is first so the default needs no lookup. */
export const WARDROBE_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'shirt', label: 'Tops' },
  { id: 'trousers', label: 'Bottoms' },
  { id: 'shoes', label: 'Shoes' },
  { id: 'outerwear', label: 'Outerwear' },
  { id: 'accessory', label: 'Accessories' },
] as const;

const FILTER_CATEGORIES: Record<string, readonly string[]> = {
  shirt: ['shirt', 'knitwear', 'dress'],
  trousers: ['trousers', 'jeans'],
  shoes: ['shoes'],
  outerwear: ['blazer', 'coat'],
  accessory: ['bag', 'accessory'],
};

export function filterWardrobe(
  garments: readonly SampleGarment[],
  filterId: string,
): readonly SampleGarment[] {
  if (filterId === 'all') return garments;
  const categories = FILTER_CATEGORIES[filterId] ?? [];
  return garments.filter((garment) => categories.includes(garment.category));
}

export const AVAILABILITY_LABEL: Record<Availability, string | null> = {
  // The common case needs no badge; only the exceptions are worth the ink.
  available: null,
  laundry: 'In the wash',
  unavailable: 'Unavailable',
  archived: 'Archived',
};

/**
 * Which semantic colour each state reads in.
 *
 * `laundry` is a warning, not a failure: the garment is fine and will be back.
 * `unavailable` is the one that actually costs the user an outfit, so it is
 * the only state that earns `danger`. `archived` is a deliberate choice by the
 * user and reads neutral, because colouring a decision they made implies
 * something went wrong.
 *
 * Returning a token name rather than a colour keeps this file free of hex and
 * lets the caller resolve it for the current scheme.
 */
export const AVAILABILITY_TONE: Record<
  Availability,
  'success' | 'warning' | 'danger' | 'muted'
> = {
  available: 'success',
  laundry: 'warning',
  unavailable: 'danger',
  archived: 'muted',
};
