import { coverFor } from './imagery';
import type { OutfitPiece, OutfitRecord, Slot } from '@/features/taxonomy';
import { SAMPLE_WARDROBE } from '@/features/wardrobe/sample';

/**
 * The looks behind the Discover tiles.
 *
 * Each tile is an outfit, not just a photograph, so tapping it can show what it is
 * actually made of. The pieces are the point: "streetwear" tells you nothing
 * actionable, whereas "boxy graphic tee, wide cargos, chunky trainers, bomber" is
 * something you can look for in your own wardrobe or search for online.
 *
 * `styleEvidence` is what justifies the aesthetic labels. It is shown to the user
 * rather than kept internal, because a label you cannot interrogate is not useful —
 * and if we have called something preppy for a reason the user disagrees with, they
 * should be able to see the reason.
 *
 * Pieces are matched against the sample wardrobe by name where possible, so the
 * detail screen can honestly say "you own this" versus "find this". That match is
 * the whole bridge from inspiration to a wearable outfit.
 */

interface PieceSeed {
  name: string;
  categoryId: string;
  slot: Slot;
  role: string;
  colour: string | null;
}

/** Sample-wardrobe names, lowercased, for the owned/not-owned check. */
const OWNED_BY_NAME = new Map(
  SAMPLE_WARDROBE.map((garment) => [garment.name.toLowerCase(), garment]),
);

function toPiece(seed: PieceSeed, lookId: string, index: number): OutfitPiece {
  const owned = OWNED_BY_NAME.get(seed.name.toLowerCase());
  return {
    id: owned ? owned.id : `${lookId}-piece-${index}`,
    name: seed.name,
    categoryId: seed.categoryId,
    slot: seed.slot,
    role: seed.role,
    colour: seed.colour,
    owned: Boolean(owned),
    image: owned?.image ?? null,
    blurhash: owned?.blurhash ?? null,
  };
}

interface LookSeed {
  id: string;
  title: string;
  aesthetics: readonly string[];
  dressCode: string;
  occasions: readonly string[];
  styleEvidence: readonly string[];
  pieces: readonly PieceSeed[];
}

const SEEDS: readonly LookSeed[] = [
  {
    id: 'streetwear',
    title: 'Streetwear',
    aesthetics: ['streetwear'],
    dressCode: 'casual',
    occasions: ['everyday', 'social'],
    styleEvidence: ['relaxed proportions', 'graphic top', 'cargo trousers', 'statement trainers'],
    pieces: [
      { name: 'Boxy graphic tee', categoryId: 'tshirt', slot: 'tops', role: 'top', colour: 'charcoal' },
      { name: 'Wide cargo trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'olive' },
      { name: 'Charcoal bomber jacket', categoryId: 'jacket', slot: 'outerwear', role: 'outer', colour: 'charcoal' },
      { name: 'Chunky white trainers', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'white' },
      { name: 'Crossbody bag', categoryId: 'bag', slot: 'accessories', role: 'bag', colour: 'black' },
    ],
  },
  {
    id: 'casual',
    title: 'Casual',
    aesthetics: ['classic', 'minimalist'],
    dressCode: 'casual',
    occasions: ['everyday', 'weekend'],
    styleEvidence: ['straight denim', 'simple knit', 'clean trainers'],
    pieces: [
      { name: 'Striped fine knit', categoryId: 'knitwear', slot: 'tops', role: 'top', colour: 'navy' },
      { name: 'Indigo straight jeans', categoryId: 'jeans', slot: 'bottoms', role: 'bottom', colour: 'indigo' },
      { name: 'White leather trainers', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'white' },
    ],
  },
  {
    id: 'smart-casual',
    title: 'Smart casual',
    aesthetics: ['classic', 'preppy'],
    dressCode: 'smart_casual',
    occasions: ['dinner', 'meeting', 'everyday'],
    styleEvidence: ['unstructured blazer', 'fine-gauge knit', 'loafers'],
    pieces: [
      { name: 'Navy wool blazer', categoryId: 'blazer', slot: 'outerwear', role: 'outer', colour: 'navy' },
      { name: 'Striped fine knit', categoryId: 'knitwear', slot: 'tops', role: 'top', colour: 'navy' },
      { name: 'Cream wide-leg trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'cream' },
      { name: 'Brown penny loafers', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'brown' },
    ],
  },
  {
    id: 'office',
    title: 'Office',
    aesthetics: ['classic', 'elegant', 'minimalist'],
    dressCode: 'business_casual',
    occasions: ['work', 'meeting'],
    styleEvidence: ['tailored trousers', 'crisp shirting', 'structured bag', 'low heel'],
    pieces: [
      { name: 'White poplin shirt', categoryId: 'shirt', slot: 'tops', role: 'top', colour: 'white' },
      { name: 'Cream wide-leg trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'cream' },
      { name: 'Navy wool blazer', categoryId: 'blazer', slot: 'outerwear', role: 'outer', colour: 'navy' },
      { name: 'Tan leather tote', categoryId: 'bag', slot: 'accessories', role: 'bag', colour: 'tan' },
      { name: 'Brown penny loafers', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'brown' },
    ],
  },
  {
    id: 'formal',
    title: 'Formal',
    aesthetics: ['classic', 'elegant'],
    dressCode: 'business_formal',
    occasions: ['ceremony', 'interview'],
    styleEvidence: ['matched suit', 'crisp shirt', 'polished leather', 'minimal jewellery'],
    pieces: [
      { name: 'Midnight navy suit jacket', categoryId: 'blazer', slot: 'outerwear', role: 'outer', colour: 'navy' },
      { name: 'Matching suit trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'navy' },
      { name: 'White poplin shirt', categoryId: 'shirt', slot: 'tops', role: 'top', colour: 'white' },
      { name: 'Black leather oxfords', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'black' },
    ],
  },
  {
    id: 'evening',
    title: 'Evening',
    aesthetics: ['glamorous', 'elegant'],
    dressCode: 'cocktail',
    occasions: ['evening', 'party'],
    styleEvidence: ['satin drape', 'fine gold chain', 'heeled sandal'],
    pieces: [
      { name: 'Burgundy satin slip dress', categoryId: 'dress', slot: 'tops', role: 'dress', colour: 'burgundy' },
      { name: 'Strappy heeled sandals', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'black' },
      { name: 'Small clutch', categoryId: 'bag', slot: 'accessories', role: 'bag', colour: 'black' },
    ],
  },
  {
    id: 'athleisure',
    title: 'Athleisure',
    aesthetics: ['athleisure', 'sporty'],
    dressCode: 'casual',
    occasions: ['everyday', 'travel'],
    styleEvidence: ['technical outerwear', 'leggings', 'running shoes'],
    pieces: [
      { name: 'Technical running jacket', categoryId: 'jacket', slot: 'outerwear', role: 'outer', colour: 'slate' },
      { name: 'Black leggings', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'black' },
      { name: 'Running shoes', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'coral' },
    ],
  },
  {
    id: 'minimalist',
    title: 'Minimalist',
    aesthetics: ['minimalist', 'elegant'],
    dressCode: 'smart_casual',
    occasions: ['everyday', 'dinner'],
    styleEvidence: ['neutral palette', 'column silhouette', 'unbranded leather'],
    pieces: [
      { name: 'Stone-grey long coat', categoryId: 'coat', slot: 'outerwear', role: 'outer', colour: 'stone' },
      { name: 'White poplin shirt', categoryId: 'shirt', slot: 'tops', role: 'top', colour: 'white' },
      { name: 'Cream wide-leg trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'cream' },
      { name: 'Flat leather sandals', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'tan' },
    ],
  },
  {
    id: 'warm-weather',
    title: 'Warm weather',
    aesthetics: ['resort', 'minimalist'],
    dressCode: 'casual',
    occasions: ['holiday', 'everyday'],
    styleEvidence: ['linen', 'open weave', 'light colours', 'flat sandals'],
    pieces: [
      { name: 'Sand linen shirt', categoryId: 'shirt', slot: 'tops', role: 'top', colour: 'sand' },
      { name: 'Wide linen trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'sand' },
      { name: 'Flat leather sandals', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'tan' },
      { name: 'Woven straw bag', categoryId: 'bag', slot: 'accessories', role: 'bag', colour: 'natural' },
    ],
  },
  {
    id: 'rainy-season',
    title: 'Rainy season',
    aesthetics: ['utility', 'outdoor'],
    dressCode: 'casual',
    occasions: ['everyday', 'commute'],
    styleEvidence: ['water-resistant shell', 'cropped hem', 'closed shoe', 'dark base'],
    pieces: [
      { name: 'Olive hooded shell jacket', categoryId: 'jacket', slot: 'outerwear', role: 'outer', colour: 'olive' },
      { name: 'Cropped dark trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'charcoal' },
      { name: 'Leather boots', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'brown' },
    ],
  },
  {
    id: 'modest',
    title: 'Modest',
    aesthetics: ['minimalist', 'elegant'],
    dressCode: 'smart_casual',
    occasions: ['everyday', 'worship', 'work'],
    styleEvidence: ['full coverage', 'loose cut', 'high neckline', 'long sleeve'],
    pieces: [
      { name: 'Sand longline layer', categoryId: 'coat', slot: 'outerwear', role: 'outer', colour: 'sand' },
      { name: 'High-neck cream top', categoryId: 'blouse', slot: 'tops', role: 'top', colour: 'cream' },
      { name: 'Loose wide trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'cream' },
      { name: 'Flat leather shoes', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'tan' },
    ],
  },
  {
    id: 'heritage',
    title: 'Heritage & print',
    aesthetics: ['heritage_print', 'maximalist'],
    dressCode: 'smart_casual',
    occasions: ['celebration', 'everyday'],
    styleEvidence: ['woven print', 'solid pairing', 'sculptural accessory'],
    pieces: [
      { name: 'Kitenge print jacket', categoryId: 'blazer', slot: 'outerwear', role: 'outer', colour: 'ochre' },
      { name: 'Plain black trousers', categoryId: 'trousers', slot: 'bottoms', role: 'bottom', colour: 'black' },
      { name: 'Leather sandals', categoryId: 'shoes', slot: 'shoes', role: 'shoes', colour: 'brown' },
      { name: 'Brass earrings', categoryId: 'accessory', slot: 'accessories', role: 'accessory', colour: 'brass' },
    ],
  },
];

export interface Look extends OutfitRecord {
  /** The generated cover shown on the tile and at the top of the detail screen. */
  cover: ReturnType<typeof coverFor>;
}

export const LOOKS: readonly Look[] = SEEDS.map((seed) => ({
  id: seed.id,
  title: seed.title,
  aesthetics: seed.aesthetics,
  dressCode: seed.dressCode,
  occasions: seed.occasions,
  styleEvidence: seed.styleEvidence,
  pieces: seed.pieces.map((piece, index) => toPiece(piece, seed.id, index)),
  isGenerated: true,
  cover: coverFor(seed.id, seed.title),
}));

const BY_ID = new Map(LOOKS.map((look) => [look.id, look]));

export function lookById(id: string): Look | undefined {
  return BY_ID.get(id);
}

/** How many pieces of this look the user already owns. Drives the bridge copy. */
export function ownedCount(look: Look): number {
  return look.pieces.filter((piece) => piece.owned).length;
}
