/**
 * The dimensions an outfit is described along.
 *
 * The load-bearing idea, and the one that changes the data model: **these are
 * independent axes, not one category.** "Streetwear", "elegant", "casual" and
 * "farm work clothing" are answers to four different questions, and an outfit has an
 * answer to each. Forcing them into a single `category` field is what makes a
 * wardrobe app give useless advice — it cannot represent a minimalist outfit that is
 * also business formal, or modest streetwear.
 *
 * The same white shirt is classic with navy chinos and loafers, business formal
 * under a charcoal suit, streetwear oversized with baggy jeans, and bohemian with a
 * printed skirt. The garment did not change; the combination did. So aesthetics
 * attach to *outfits*, while garments carry only what is true of the item itself.
 *
 * Two rules that follow, and that the code enforces:
 *
 * 1. **Aesthetic is multi-label.** A navy trouser suit can be classic, elegant,
 *    minimalist and preppy at once. A single-label model would have to pick, and
 *    whichever it picked would be arguable.
 * 2. **Requirements outrank taste.** Activity and prescribed clothing come first,
 *    then fit and coverage, then weather, then availability, then dress code, and
 *    only then preferred aesthetics. A beautiful outfit the user cannot wear today
 *    is a failure, not a near miss.
 */

/** Which question a dimension answers. Kept explicit so new axes slot in cleanly. */
export type DimensionKind =
  | 'garment'
  | 'construction'
  | 'colour'
  | 'material'
  | 'aesthetic'
  | 'presentation'
  | 'dress_code'
  | 'occasion'
  | 'environment'
  | 'wearer_requirement'
  | 'availability';

/**
 * Where an attribute came from. §5 requires inferred and confirmed values to stay
 * separate, and this is how: every attribute records its own provenance, so a user
 * correction can never be overwritten by a later, more confident model guess.
 */
export type AttributeSource =
  /** Read from an image by a model. Always carries a confidence. */
  | 'inferred'
  /** Stated by the user. Outranks everything. */
  | 'confirmed'
  /** From a retailer feed or product page. */
  | 'catalogue'
  /** From a care or size label the user photographed. */
  | 'label';

export interface Attributed<T> {
  value: T;
  source: AttributeSource;
  /** 0–1. Only meaningful when `source` is 'inferred'. */
  confidence?: number;
}

/**
 * The order recommendations must be resolved in.
 *
 * Deliberately a constant rather than scattered conditionals: it is a product rule,
 * it gets argued about, and it needs to be visible in one place when it is.
 */
export const RESOLUTION_ORDER = [
  'activity_requirements',
  'fit_and_accessibility',
  'weather',
  'availability',
  'dress_code',
  'aesthetic_preference',
  'variety_and_feedback',
  'shopping_suggestions',
] as const;

export type ResolutionStage = (typeof RESOLUTION_ORDER)[number];

/**
 * Things an image genuinely cannot establish.
 *
 * Listed so no inference path quietly claims one. A photograph can suggest "shiny
 * fabric"; it cannot establish fibre composition, waterproofing, size, or whether
 * the wearer finds the outfit appropriate. Claiming otherwise is how a styling app
 * tells someone their jacket is waterproof and they get soaked.
 */
export const NOT_INFERABLE_FROM_IMAGE = [
  'fibre_composition',
  'exact_size',
  'waterproof_performance',
  'thermal_rating',
  'comfort',
  'price',
  'brand_authenticity',
  'wearer_approval',
] as const;

/**
 * Inferences that must never be drawn, whatever the model proposes.
 *
 * An aesthetic describes clothing. It says nothing about the person wearing it, and
 * a gothic outfit is not evidence of anything about religion, character or mental
 * health. Enforced as a denylist rather than left to prompt wording.
 */
export const FORBIDDEN_INFERENCES = [
  'religion',
  'ethnicity',
  'income',
  'mental_health',
  'character',
  'subculture_membership',
  'sexual_orientation',
  'political_affiliation',
] as const;

export function isForbiddenInference(field: string): boolean {
  const normalised = field.toLowerCase().replace(/[\s-]+/g, '_');
  return FORBIDDEN_INFERENCES.some((forbidden) => normalised.includes(forbidden));
}
