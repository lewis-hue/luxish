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

/**
 * How a collection is browsed, after how comparable apps
 * organise fashion.
 *
 * Department-store sections are not how anybody searches. These three
 * lenses are, and they map onto the two questions this app exists to
 * answer: what do I wear to this, and how do I style what I own.
 *
 * - `aesthetic`: what look is this
 * - `occasion`: where am I going
 * - `formula`: how do I get more out of what I already have
 */
export type Lens = 'aesthetic' | 'occasion' | 'formula';

export interface StyleCategory extends Omit<StyleCollection, 'cover'> {
  /** Null until an inspiration source is licensed and configured. */
  cover: StyleCollection['cover'] | null;
  lens: Lens;
  formality: Formality;
  seasons: readonly Season[];
  /** Short, concrete garment cues the stylist can anchor on. */
  cues: readonly string[];
}

export const STYLE_CATEGORIES: readonly StyleCategory[] = [
  {
    id: 'streetwear',
    title: 'Streetwear',
    subtitle: 'Oversized layers, statement footwear, graphics that mean something',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['cool', 'transitional'],
    cues: ['oversized outerwear', 'graphic layers', 'statement trainers', 'cargo trousers'],
  },
  {
    id: 'quiet-luxury',
    title: 'Quiet luxury',
    subtitle: 'Old money dressing: no logos, very good cloth',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['camel overcoat', 'cashmere roll-neck', 'unbranded tailoring', 'leather loafers'],
  },
  {
    id: 'clean-girl',
    title: 'Clean girl',
    subtitle: 'Crisp, pared back, nothing fighting for attention',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['warm', 'all_year'],
    cues: ['white shirt', 'straight ivory trousers', 'gold jewellery', 'leather slides'],
  },
  {
    id: 'downtown-romantic',
    title: 'Downtown romantic',
    subtitle: 'Hard edges softened with lace and vintage detail',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['cool', 'transitional'],
    cues: ['leather jacket', 'lace top', 'pleated mini skirt', 'knee-high boots'],
  },
  {
    id: 'dark-academia',
    title: 'Dark academia',
    subtitle: 'Tweed, wool and a satchel, for weather that turns',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['cool'],
    cues: ['tweed blazer', 'roll-neck', 'pleated trousers', 'leather brogues'],
  },
  {
    id: 'gorpcore',
    title: 'Gorpcore',
    subtitle: 'Technical outdoor kit, worn nowhere near a mountain',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['cool', 'transitional'],
    cues: ['shell jacket', 'zip fleece', 'wide cargo trousers', 'trail runners'],
  },
  {
    id: 'blokecore',
    title: 'Blokecore',
    subtitle: 'Vintage football shirts and straight jeans',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['all_year'],
    cues: ['football shirt', 'straight jeans', 'retro trainers', 'track jacket'],
  },
  {
    id: 'y2k',
    title: 'Y2K',
    subtitle: 'Low-rise, baggy, unmistakably early 2000s',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['warm', 'transitional'],
    cues: ['low-rise baggy denim', 'baby tee', 'shoulder bag', 'chunky trainers'],
  },
  {
    id: 'minimalist',
    title: 'Minimalist',
    subtitle: 'Few pieces, each one correct',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['clean lines', 'neutral palette', 'structured coat', 'simple knit'],
  },
  {
    id: 'monochrome',
    title: 'Monochrome',
    subtitle: 'One colour, carried from collar to shoe',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['all black', 'wide trousers', 'loafers', 'matched tones'],
  },
  {
    id: 'heritage',
    title: 'Heritage & print',
    subtitle: 'Traditional cloth and cut, worn now',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['African print', 'ankara', 'kaftan', 'regional tailoring'],
  },
  {
    id: 'modest',
    title: 'Modest',
    subtitle: 'Full coverage, nothing sacrificed',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['long sleeves', 'long hems', 'loose silhouettes', 'considered layering'],
  },
  {
    id: 'wedding-guest',
    title: 'Wedding guest',
    subtitle: 'Sharp, and never upstaging the couple',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'formal',
    seasons: ['warm', 'transitional'],
    cues: ['column dress', 'well-cut suit', 'nothing white', 'comfortable heels'],
  },
  {
    id: 'festival',
    title: 'Festival & concert',
    subtitle: 'Long days outside, on your feet',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'casual',
    seasons: ['warm'],
    cues: ['denim shorts', 'cowboy boots', 'patterned shirt', 'cropped knit'],
  },
  {
    id: 'office-siren',
    title: 'Office siren',
    subtitle: 'Late-90s corporate, sharpened',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'business',
    seasons: ['all_year'],
    cues: ['pinstripe blazer', 'pencil skirt', 'fine glasses', 'pointed heels'],
  },
  {
    id: 'date-night',
    title: 'Date night',
    subtitle: 'Dressed up without looking like you tried',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'smart_casual',
    seasons: ['warm', 'transitional'],
    cues: ['silk slip dress', 'fine cardigan', 'heeled sandals', 'small bag'],
  },
  {
    id: 'evening',
    title: 'Evening',
    subtitle: 'Black tie, and the things that pass for it',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'black_tie',
    seasons: ['all_year'],
    cues: ['floor-length', 'dinner jacket', 'fine jewellery', 'evening shoes'],
  },
  {
    id: 'travel',
    title: 'Airport & travel',
    subtitle: 'Comfort that still looks like clothes',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'casual',
    seasons: ['all_year'],
    cues: ['wide trousers', 'loose shirt', 'knit set', 'leather holdall'],
  },
  {
    id: 'office',
    title: 'Workwear',
    subtitle: 'What the office actually asks for',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'business',
    seasons: ['all_year'],
    cues: ['blazer', 'tailored trousers', 'shirting', 'leather shoes'],
  },
  {
    id: 'capsule',
    title: 'Capsule wardrobe',
    subtitle: 'Thirty pieces that all work together',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['white shirt', 'navy knit', 'straight trousers', 'beige trench'],
  },
  {
    id: 'denim',
    title: 'Elevated denim',
    subtitle: 'Jeans and a nice top, done properly',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'casual',
    seasons: ['all_year'],
    cues: ['straight-leg jeans', 'denim jacket', 'plain tee', 'worn boots'],
  },
  {
    id: 'tailoring',
    title: 'Tailoring',
    subtitle: 'Suiting worn properly, shoulders doing the work',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'business',
    seasons: ['all_year'],
    cues: ['single-breasted jacket', 'wool trousers', 'fine knit', 'leather derbies'],
  },
  {
    id: 'layering',
    title: 'Layering',
    subtitle: 'Three weights at once, for weather that cannot decide',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'smart_casual',
    seasons: ['cool', 'transitional'],
    cues: ['wool overcoat', 'roll-neck', 'mid-weight jacket', 'leather boots'],
  },
  {
    id: 'athleisure',
    title: 'Athleisure',
    subtitle: 'Sportswear that leaves the gym',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'casual',
    seasons: ['all_year'],
    cues: ['technical knit', 'track trousers', 'clean trainers', 'zip layer'],
  },
  {
    id: 'utility',
    title: 'Utility',
    subtitle: 'Workwear shapes, pockets that hold things',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'casual',
    seasons: ['transitional'],
    cues: ['chore jacket', 'work shirt', 'cargo trousers', 'sturdy boots'],
  },
  {
    id: 'colour',
    title: 'Colour',
    subtitle: 'Bold, held to a few tones that agree',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'casual',
    seasons: ['warm', 'transitional'],
    cues: ['burgundy knit', 'ochre trousers', 'tan leather', 'muted brights'],
  },
  {
    id: 'couples',
    title: 'Dressing together',
    subtitle: 'Two outfits that belong together without matching',
    cover: null,
    lookCount: null,
    lens: 'occasion',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['complementary tones', 'shared palette', 'one statement each', 'coats that agree'],
  },
  // -- what this audience is actually wearing ------------------------------ #
  //
  // Added with their covers, after the welcome screen was recast for the
  // people this app is for. The aesthetics above are a reasonable map of
  // fashion; these came up through TikTok rather than through a magazine,
  // and `smart-casual` and `elevated-basics` are the register the same
  // people wear to everything that is not a night out.
  {
    id: 'coquette',
    title: 'Coquette',
    subtitle: 'Ribbons, lace and a lot of cream',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['warm', 'transitional'],
    cues: ['ruffled blouse', 'satin ribbon', 'pleated mini skirt', 'ballet flats'],
  },
  {
    id: 'balletcore',
    title: 'Balletcore',
    subtitle: 'Wrap cardigans, long skirts, legwarmers',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['cool', 'transitional'],
    cues: ['wrap cardigan', 'bodysuit', 'long soft skirt', 'ballet flats'],
  },
  {
    id: 'mob-wife',
    title: 'Mob wife',
    subtitle: 'Fur, gold and sunglasses indoors',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'smart_casual',
    seasons: ['cool'],
    cues: ['faux-fur coat', 'slip dress', 'gold jewellery', 'heeled boots'],
  },
  {
    id: 'techwear',
    title: 'Techwear',
    subtitle: 'Taped seams, straps, everything black',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['cool', 'transitional'],
    cues: ['shell jacket', 'harness strap', 'ripstop trousers', 'heavy-soled boots'],
  },
  {
    id: 'skater',
    title: 'Skater',
    subtitle: 'Loose everything, shoes with a history',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['transitional', 'all_year'],
    cues: ['graphic tee', 'wide-leg jeans', 'beanie', 'skate shoes'],
  },
  {
    id: 'grunge',
    title: 'Grunge',
    subtitle: 'Flannel over a band tee, boots that have been worn',
    cover: null,
    lookCount: null,
    lens: 'aesthetic',
    formality: 'casual',
    seasons: ['cool', 'transitional'],
    cues: ['oversized flannel', 'band tee', 'ripped jeans', 'lace-up boots'],
  },
  {
    id: 'smart-casual',
    title: 'Smart casual',
    subtitle: 'A blazer with trainers, and it works',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['relaxed blazer', 'fine knit', 'tailored trousers', 'leather trainers'],
  },
  {
    id: 'elevated-basics',
    title: 'Elevated basics',
    subtitle: 'Plain pieces, cut properly, no logos',
    cover: null,
    lookCount: null,
    lens: 'formula',
    formality: 'smart_casual',
    seasons: ['all_year'],
    cues: ['heavyweight tee', 'straight trousers', 'minimal sneakers', 'no branding'],
  },
] as const;

export function categoryById(id: string): StyleCategory | undefined {
  return STYLE_CATEGORIES.find((c) => c.id === id);
}
