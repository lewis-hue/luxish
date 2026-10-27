/**
 * Aesthetic categories — the visual language of a complete look.
 *
 * Multi-label by design. A navy trouser suit with a plain blouse is plausibly
 * classic, elegant, minimalist *and* preppy; a model forced to pick one would pick
 * arguably. Overlap is the normal case, not an error to resolve.
 *
 * `cues` are supporting signals, never requirements — no single cue makes an outfit
 * streetwear, and an outfit can be streetwear without any particular one. They exist
 * to drive annotation guidance and to explain a label back to the user ("called this
 * streetwear because: relaxed proportions, graphic top, statement trainers"), which
 * is far more useful than an unexplained tag.
 *
 * `confusableWith` records the neighbours a reviewer most often has to choose
 * between. Those pairs are where annotation disagreement concentrates, so naming
 * them is what lets the guide be written once rather than relitigated per image.
 */

export type AestheticFamily =
  | 'classic'
  | 'street'
  | 'expressive'
  | 'regional_leisure'
  | 'era';

export interface Aesthetic {
  id: string;
  label: string;
  family: AestheticFamily;
  /** One sentence a reviewer can apply consistently. */
  definition: string;
  /** Supporting signals. Never individually required. */
  cues: readonly string[];
  /** Neighbours this is most often confused with, and which must be distinguished. */
  confusableWith?: readonly string[];
}

export const AESTHETICS: readonly Aesthetic[] = [
  // --- Classic, polished, academic -----------------------------------------
  {
    id: 'classic',
    label: 'Classic',
    family: 'classic',
    definition: 'Familiar tailoring, balanced proportions, restrained detail.',
    cues: ['oxford shirt', 'straight chinos', 'penny loafers', 'navy blazer'],
    confusableWith: ['elegant', 'preppy', 'minimalist'],
  },
  {
    id: 'elegant',
    label: 'Elegant',
    family: 'classic',
    definition:
      'Considered fit, controlled drape and harmonious coordination. A description of the outfit, never a judgement of the person.',
    cues: ['controlled drape', 'tonal coordination', 'restrained accessories'],
    confusableWith: ['classic', 'minimalist', 'glamorous'],
  },
  {
    id: 'minimalist',
    label: 'Minimalist',
    family: 'classic',
    definition: 'Clean shapes, limited ornament, few competing elements.',
    cues: ['tonal palette', 'unbranded', 'simple silhouette', 'few pieces'],
    confusableWith: ['elegant', 'classic'],
  },
  {
    id: 'preppy',
    label: 'Preppy',
    family: 'classic',
    definition: 'Collegiate references: shirting, knitwear, chinos, stripes, checks.',
    cues: ['oxford shirt', 'sweater vest', 'pleated skirt', 'cable knit', 'loafers'],
    confusableWith: ['classic', 'academia'],
  },
  {
    id: 'academia',
    label: 'Academia',
    family: 'classic',
    definition: 'Academic tailoring, knit layers, textured fabrics, bookish styling.',
    cues: ['tweed blazer', 'sweater vest', 'pleated midi', 'derby shoes'],
    confusableWith: ['preppy', 'classic'],
  },

  // --- Street, sport, utility, outdoor -------------------------------------
  {
    id: 'streetwear',
    label: 'Streetwear',
    family: 'street',
    definition:
      'Relaxed or deliberate proportions with graphic and sportswear references. Culturally broad, not one oversized silhouette.',
    cues: ['graphic tee', 'hoodie', 'cargo trousers', 'statement trainers', 'bomber'],
    confusableWith: ['skate', 'athleisure', 'y2k'],
  },
  {
    id: 'skate',
    label: 'Skate-inspired',
    family: 'street',
    definition: 'Movement-friendly trousers, graphic tees, overshirts, skate shoes.',
    cues: ['loose straight chinos', 'plaid overshirt', 'skate shoes', 'crew socks'],
    confusableWith: ['streetwear', 'grunge'],
  },
  {
    id: 'athleisure',
    label: 'Athleisure',
    family: 'street',
    definition: 'Athletic clothing styled for ordinary daily wear, not for sport.',
    cues: ['joggers', 'leggings', 'zip sweatshirt', 'trainers'],
    confusableWith: ['sporty', 'streetwear'],
  },
  {
    id: 'sporty',
    label: 'Sporty',
    family: 'street',
    definition:
      'Visible sports references worn as fashion. Distinct from performance sportswear, which must actually suit the sport.',
    cues: ['team jersey', 'track stripes', 'warm-up jacket'],
    confusableWith: ['athleisure'],
  },
  {
    id: 'utility',
    label: 'Utility',
    family: 'street',
    definition:
      'Workwear-inspired: patch pockets, chore jackets, robust textures. Inspired by work clothing, not certified as protective.',
    cues: ['chore jacket', 'carpenter trousers', 'coverall', 'lace-up boots'],
    confusableWith: ['outdoor', 'techwear'],
  },
  {
    id: 'outdoor',
    label: 'Outdoor',
    family: 'street',
    definition:
      'Fleece, shell jackets, hiking trousers, trail footwear. An outdoor *look* does not establish weather performance.',
    cues: ['fleece', 'shell jacket', 'hiking trousers', 'trail shoes'],
    confusableWith: ['techwear', 'utility'],
  },
  {
    id: 'techwear',
    label: 'Techwear',
    family: 'street',
    definition: 'Articulated cuts, functional pockets, streamlined technical surfaces.',
    cues: ['articulated cargos', 'angular shell', 'sling bag', 'monochrome'],
    confusableWith: ['outdoor', 'utility'],
  },

  // --- Romantic, expressive, music-associated ------------------------------
  {
    id: 'bohemian',
    label: 'Bohemian',
    family: 'expressive',
    definition: 'Flowing shapes, embroidery, relaxed layering, patterned textiles.',
    cues: ['maxi skirt', 'embroidery', 'crochet', 'flat leather sandals'],
    confusableWith: ['romantic', 'cottagecore'],
  },
  {
    id: 'romantic',
    label: 'Romantic',
    family: 'expressive',
    definition: 'Soft drape, gathers, delicate prints, ruffles, lace or bows.',
    cues: ['floral print', 'puff sleeve', 'lace', 'ballet flats'],
    confusableWith: ['cottagecore', 'bohemian'],
  },
  {
    id: 'cottagecore',
    label: 'Cottagecore',
    family: 'expressive',
    definition: 'Pastoral references: gingham, small florals, pinafores, gentle volume.',
    cues: ['gingham', 'pinafore', 'puff sleeve', 'ankle boots'],
    confusableWith: ['romantic', 'bohemian'],
  },
  {
    id: 'rocker',
    label: 'Rocker',
    family: 'expressive',
    definition: 'Biker jackets, band graphics, denim, boots.',
    cues: ['biker jacket', 'band tee', 'dark denim', 'chelsea boots'],
    confusableWith: ['punk', 'grunge'],
  },
  {
    id: 'punk',
    label: 'Punk-inspired',
    family: 'expressive',
    definition: 'DIY patches, tartan, distressed surfaces, contrasting hardware.',
    cues: ['patches', 'tartan', 'customised denim', 'lace-up boots'],
    confusableWith: ['rocker', 'grunge'],
  },
  {
    id: 'grunge',
    label: 'Grunge',
    family: 'expressive',
    definition: 'Relaxed, deliberately unpolished layers: flannel, faded denim.',
    cues: ['flannel overshirt', 'faded denim', 'worn boots', 'layering'],
    confusableWith: ['skate', 'rocker'],
  },
  {
    id: 'gothic',
    label: 'Gothic-inspired',
    family: 'expressive',
    definition:
      'Dark palettes, dramatic shapes, lace and velvet. Describes clothing only, never the wearer.',
    cues: ['black palette', 'velvet', 'lace', 'flat boots'],
    confusableWith: ['rocker', 'avant_garde'],
  },

  // --- Regional inspiration, leisure, statement ----------------------------
  {
    id: 'western',
    label: 'Western-inspired',
    family: 'regional_leisure',
    definition: 'Yokes, snap shirts, denim, bootcut shapes, cowboy boots.',
    cues: ['western yoke', 'snap buttons', 'bootcut', 'cowboy boots'],
  },
  {
    id: 'nautical',
    label: 'Nautical',
    family: 'regional_leisure',
    definition: 'Maritime stripes, navy and cream, relaxed tailoring.',
    cues: ['breton stripe', 'navy and cream', 'deck shoes'],
  },
  {
    id: 'resort',
    label: 'Resort',
    family: 'regional_leisure',
    definition: 'Relaxed warm-weather separates, light layers, easy shapes.',
    cues: ['linen', 'camp collar', 'sandals', 'sun hat'],
    confusableWith: ['nautical'],
  },
  {
    id: 'glamorous',
    label: 'Glamorous',
    family: 'regional_leisure',
    definition: 'Shine, embellishment, dramatic colour or volume for occasions.',
    cues: ['sequins', 'satin', 'velvet', 'statement volume'],
    confusableWith: ['elegant'],
  },
  {
    id: 'maximalist',
    label: 'Maximalist',
    family: 'regional_leisure',
    definition: 'Layered colours, prints, textures and statement details.',
    cues: ['mixed prints', 'high colour contrast', 'statement accessories'],
    confusableWith: ['bohemian'],
  },
  {
    id: 'avant_garde',
    label: 'Avant-garde',
    family: 'regional_leisure',
    definition: 'Asymmetry, unusual volume, unconventional construction.',
    cues: ['asymmetric hem', 'sculptural volume', 'unexpected construction'],
    confusableWith: ['minimalist', 'gothic'],
  },
  {
    id: 'heritage_print',
    label: 'Heritage & print',
    family: 'regional_leisure',
    definition:
      'Regional textiles and print-led looks. The textile identity is recorded separately and never replaced by this label.',
    cues: ['woven print', 'kitenge', 'artisanal detail', 'solid pairing'],
  },

  // --- Era references -------------------------------------------------------
  {
    id: 'retro_50s',
    label: "1950s-inspired",
    family: 'era',
    definition: 'Full skirts, cardigans, camp shirts, tailored trousers.',
    cues: ['fit-and-flare', 'camp collar', 'cropped cardigan'],
  },
  {
    id: 'retro_70s',
    label: "1970s-inspired",
    family: 'era',
    definition: 'Flares, earthy colours, patterned shirts, textured layers.',
    cues: ['flared leg', 'earth tones', 'suede', 'waistcoat'],
  },
  {
    id: 'retro_90s',
    label: "1990s-inspired",
    family: 'era',
    definition: 'Straight denim, relaxed sportswear, or minimal references.',
    cues: ['straight jeans', 'bomber', 'slip dress over tee'],
    confusableWith: ['minimalist', 'grunge'],
  },
  {
    id: 'y2k',
    label: 'Y2K-inspired',
    family: 'era',
    definition: 'Early-2000s references: metallics, cargo shapes, baby tees, tracksuits.',
    cues: ['metallic accents', 'cargo', 'baby tee', 'small shoulder bag'],
    confusableWith: ['streetwear'],
  },
];

/**
 * Marketing and social-media labels mapped onto stable categories.
 *
 * The user's search term is preserved rather than replaced: community usage drifts,
 * and a term that maps to `elegant` today may need its own entry later. Searching
 * "quiet luxury" should find classic outfits *and* still be recorded as having been
 * searched as "quiet luxury".
 */
export const SEARCH_ALIASES: Readonly<Record<string, readonly string[]>> = {
  chic: ['elegant', 'minimalist', 'classic'],
  'old money': ['classic', 'preppy'],
  'quiet luxury': ['classic', 'minimalist'],
  'dark academia': ['academia', 'gothic'],
  'light academia': ['academia'],
  coquette: ['romantic'],
  normcore: ['minimalist'],
  gorpcore: ['outdoor'],
  retro: ['retro_50s', 'retro_70s', 'retro_90s'],
};

const BY_ID = new Map(AESTHETICS.map((aesthetic) => [aesthetic.id, aesthetic]));

export function aestheticById(id: string): Aesthetic | undefined {
  return BY_ID.get(id);
}

/** Resolves a user's search term to candidate aesthetics, aliases included. */
export function resolveAestheticSearch(term: string): readonly Aesthetic[] {
  const normalised = term.trim().toLowerCase();
  if (!normalised) return [];

  const aliased = SEARCH_ALIASES[normalised];
  if (aliased) {
    return aliased.map((id) => BY_ID.get(id)).filter((a): a is Aesthetic => Boolean(a));
  }

  const direct = BY_ID.get(normalised.replace(/[\s-]+/g, '_'));
  if (direct) return [direct];

  return AESTHETICS.filter(
    (aesthetic) =>
      aesthetic.label.toLowerCase().includes(normalised) ||
      aesthetic.cues.some((cue) => cue.includes(normalised)),
  );
}
