/**
 * Dress codes — the expected convention of dress.
 *
 * Stored entirely separately from aesthetics, because they vary independently: a
 * minimalist outfit can be casual, business formal or black tie. Collapsing the two
 * is what produces advice like "wear something minimalist to the wedding", which
 * answers the wrong question.
 *
 * Two distinctions the guide is emphatic about and that the code preserves:
 *
 * - **Smart casual is not business casual.** Smart casual is a polished informal
 *   look anywhere; business casual is tied to one workplace's expectations, where
 *   denim or trainers may be fine or may not. Only the employer settles it.
 * - **Cocktail is not semi-formal.** They overlap but are not synonyms, and
 *   treating them as such is how someone arrives wrong.
 *
 * `requiresClarification` marks the codes where a bare request like "something
 * formal" is genuinely ambiguous. Asking one short question there is better than
 * confidently dressing someone for the wrong event.
 */

export interface DressCode {
  id: string;
  label: string;
  /** Rough ordering for comparison. Not a quality scale. */
  formalityRank: number;
  definition: string;
  /** Neutral starting points. Examples, never uniforms. */
  startingPoints: readonly string[];
  /** True when the term alone does not determine what to wear. */
  requiresClarification?: boolean;
  /** What actually settles it when it is ambiguous. */
  settledBy?: string;
}

export const DRESS_CODES: readonly DressCode[] = [
  {
    id: 'casual',
    label: 'Casual',
    formalityRank: 1,
    definition: 'Everyday comfort with no particular convention to meet.',
    startingPoints: ['tee + jeans + trainers', 'casual dress + sandals'],
  },
  {
    id: 'smart_casual',
    label: 'Smart casual',
    formalityRank: 2,
    definition:
      'A polished informal look across settings. Distinct from business casual, which answers to one workplace.',
    startingPoints: [
      'oxford shirt or knit polo + chinos + loafers',
      'blouse + tailored trousers or midi skirt + flats',
    ],
  },
  {
    id: 'business_casual',
    label: 'Business casual',
    formalityRank: 3,
    definition:
      "Tied to an employer's expectations. Denim and trainers may be fine in one organisation and unacceptable in another.",
    startingPoints: [
      'collared shirt + tailored trousers + derby shoes',
      'blouse + tailored trousers or skirt + blazer',
    ],
    requiresClarification: true,
    settledBy: 'your workplace, not a general rule',
  },
  {
    id: 'business_formal',
    label: 'Business formal',
    formalityRank: 4,
    definition: 'Matched tailoring for professional settings.',
    startingPoints: [
      'matching navy or charcoal suit + dress shirt + polished oxfords',
      'matching trouser or skirt suit + blouse + dress shoes',
    ],
  },
  {
    id: 'semi_formal',
    label: 'Semi-formal',
    formalityRank: 5,
    definition:
      'Dressy day or evening wear. Overlaps cocktail but is not a synonym for it.',
    startingPoints: [
      'coordinated suit + collared shirt + polished shoes',
      'dressy dress, tailored jumpsuit, or coordinated dressy separates',
    ],
    requiresClarification: true,
    settledBy: 'the invitation, and whether the event is daytime or evening',
  },
  {
    id: 'cocktail',
    label: 'Cocktail',
    formalityRank: 6,
    definition: 'Evening-party dress. Tailoring and jumpsuits are included, not only dresses.',
    startingPoints: [
      'dark suit + dress shirt + polished shoes',
      'cocktail-length dress or tailored evening jumpsuit',
    ],
  },
  {
    id: 'black_tie_optional',
    label: 'Black tie optional',
    formalityRank: 7,
    definition: 'A tuxedo is welcome; a dark formal suit or formal separates also work.',
    startingPoints: [
      'tuxedo, or dark formal suit + white shirt + conservative tie',
      'formal gown, dressy cocktail dress, or formal evening separates',
    ],
  },
  {
    id: 'black_tie',
    label: 'Black tie',
    formalityRank: 8,
    definition: 'Formal evening dress with a defined conventional ensemble.',
    startingPoints: [
      'black or midnight-blue tuxedo + white formal shirt + black bow tie',
      'formal evening gown or an explicitly accepted formal ensemble',
    ],
  },
  {
    id: 'white_tie',
    label: 'White tie',
    formalityRank: 9,
    definition:
      'The most formal code, centred on the evening tailcoat. A different ensemble from black tie, not a stricter one.',
    startingPoints: [
      'evening tailcoat + formal trousers + white waistcoat + white bow tie',
      'full-length formal evening gown',
    ],
  },
];

const BY_ID = new Map(DRESS_CODES.map((code) => [code.id, code]));

export function dressCodeById(id: string): DressCode | undefined {
  return BY_ID.get(id);
}

/**
 * Whether a request like "formal" needs a clarifying question before styling.
 *
 * "Formal" maps to at least four materially different outcomes — business formal,
 * cocktail, black tie, or a locally defined ceremonial outfit. Guessing is worse
 * than one short question.
 */
export function needsClarification(term: string): string | null {
  const normalised = term.trim().toLowerCase();
  if (normalised === 'formal' || normalised === 'dressy') {
    return 'Business formal, cocktail, black tie, or a specific ceremonial outfit?';
  }
  const code = BY_ID.get(normalised.replace(/[\s-]+/g, '_'));
  return code?.requiresClarification ? (code.settledBy ?? null) : null;
}

/**
 * Additional contexts users search for directly. Deliberately not dress codes —
 * nobody calls sleepwear a dress code — but they need first-class support because
 * they are real requests.
 */
export const WEAR_CONTEXTS = [
  'loungewear',
  'sleepwear',
  'swimming',
  'running_training',
  'travel',
  'wedding_guest',
  'worship_ceremony',
  'office',
  'hospitality',
  'kitchen',
  'healthcare',
  'trades_construction',
  'remote_work',
] as const;

export type WearContext = (typeof WEAR_CONTEXTS)[number];

/**
 * Coverage preference is an **overlay**, not a category.
 *
 * A user can want modest streetwear, modest elegant dressing or modest sportswear.
 * Modelling it as its own aesthetic would make those unrepresentable, and would also
 * imply something about the wearer that is not ours to infer. The concrete
 * preferences below are what the user states; nothing is derived from anything else.
 */
export interface CoveragePreference {
  sleeveLength?: 'any' | 'short' | 'three_quarter' | 'long';
  neckline?: 'any' | 'high';
  opacity?: 'any' | 'opaque';
  garmentLength?: 'any' | 'knee' | 'midi' | 'full';
  fit?: 'any' | 'loose';
  headwear?: boolean;
}
