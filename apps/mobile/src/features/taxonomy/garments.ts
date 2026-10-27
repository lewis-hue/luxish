/**
 * Garment vocabulary — what an item *is*, independent of how it is styled.
 *
 * A garment carries only what is true of the item itself: its category, shape,
 * colour, material, measurements. It carries no aesthetic. The same white shirt is
 * classic, business formal, streetwear or bohemian depending entirely on what it is
 * worn with, so storing "streetwear" on a shirt would be wrong the moment it is worn
 * differently.
 *
 * `SLOTS` are the five buckets the wardrobe groups by and that auto-categorisation
 * classifies into. Kept deliberately few: a user scanning their wardrobe wants five
 * groups, not twenty-seven. The finer `subtypes` exist underneath for retrieval and
 * for the stylist, which does care about the difference between loafers and trainers.
 */

/** The top-level buckets shown in the wardrobe and predicted on upload. */
export const SLOTS = ['tops', 'bottoms', 'outerwear', 'shoes', 'accessories'] as const;
export type Slot = (typeof SLOTS)[number];

export const SLOT_LABELS: Record<Slot, string> = {
  tops: 'Tops',
  bottoms: 'Bottoms',
  outerwear: 'Outerwear',
  shoes: 'Shoes',
  accessories: 'Accessories',
};

export interface GarmentCategory {
  id: string;
  label: string;
  slot: Slot;
  /** Finer identities used for retrieval and styling, not shown as filters. */
  subtypes: readonly string[];
  /**
   * Roles this category can fill in an outfit. A dress fills the whole torso-and-leg
   * slot, which is why it is neither a top nor a bottom and needs saying explicitly.
   */
  outfitRoles: readonly string[];
}

export const GARMENT_CATEGORIES: readonly GarmentCategory[] = [
  // --- Tops -----------------------------------------------------------------
  {
    id: 'shirt',
    label: 'Shirt',
    slot: 'tops',
    subtypes: ['oxford', 'poplin', 'linen shirt', 'camp collar', 'western yoke', 'overshirt'],
    outfitRoles: ['top'],
  },
  {
    id: 'tshirt',
    label: 'T-shirt',
    slot: 'tops',
    subtypes: ['plain tee', 'graphic tee', 'baby tee', 'long sleeve tee'],
    outfitRoles: ['top'],
  },
  {
    id: 'knitwear',
    label: 'Knitwear',
    slot: 'tops',
    subtypes: ['jumper', 'cardigan', 'sweater vest', 'cable knit', 'turtleneck', 'polo'],
    outfitRoles: ['top', 'mid_layer'],
  },
  {
    id: 'sweatshirt',
    label: 'Sweatshirt',
    slot: 'tops',
    subtypes: ['crewneck', 'hoodie', 'zip sweatshirt'],
    outfitRoles: ['top', 'mid_layer'],
  },
  {
    id: 'blouse',
    label: 'Blouse',
    slot: 'tops',
    subtypes: ['silk blouse', 'puff sleeve', 'wrap front', 'shell top'],
    outfitRoles: ['top'],
  },
  {
    id: 'dress',
    label: 'Dress',
    slot: 'tops',
    subtypes: ['midi', 'maxi', 'slip', 'shirt dress', 'fit-and-flare', 'occasion dress'],
    // Fills torso and legs at once — the reason it cannot be a "top".
    outfitRoles: ['dress'],
  },

  // --- Bottoms --------------------------------------------------------------
  {
    id: 'trousers',
    label: 'Trousers',
    slot: 'bottoms',
    subtypes: ['tailored', 'chinos', 'wide-leg', 'pleated', 'cargo', 'joggers', 'leggings'],
    outfitRoles: ['bottom'],
  },
  {
    id: 'jeans',
    label: 'Jeans',
    slot: 'bottoms',
    subtypes: ['straight', 'slim', 'wide', 'bootcut', 'flared', 'baggy'],
    outfitRoles: ['bottom'],
  },
  {
    id: 'skirt',
    label: 'Skirt',
    slot: 'bottoms',
    subtypes: ['pleated', 'a-line', 'midi', 'maxi', 'denim', 'wrap'],
    outfitRoles: ['bottom'],
  },
  {
    id: 'shorts',
    label: 'Shorts',
    slot: 'bottoms',
    subtypes: ['tailored', 'denim', 'sports', 'cargo'],
    outfitRoles: ['bottom'],
  },

  // --- Outerwear ------------------------------------------------------------
  {
    id: 'blazer',
    label: 'Blazer',
    slot: 'outerwear',
    subtypes: ['structured', 'unstructured', 'tweed', 'double-breasted'],
    outfitRoles: ['outer', 'mid_layer'],
  },
  {
    id: 'jacket',
    label: 'Jacket',
    slot: 'outerwear',
    subtypes: ['bomber', 'biker', 'denim', 'chore', 'track', 'shell', 'fleece'],
    outfitRoles: ['outer'],
  },
  {
    id: 'coat',
    label: 'Coat',
    slot: 'outerwear',
    subtypes: ['overcoat', 'trench', 'parka', 'long coat'],
    outfitRoles: ['outer'],
  },

  // --- Shoes ----------------------------------------------------------------
  {
    id: 'shoes',
    label: 'Shoes',
    slot: 'shoes',
    subtypes: [
      'trainers',
      'loafers',
      'oxfords',
      'derbies',
      'boots',
      'chelsea boots',
      'sandals',
      'heels',
      'flats',
      'skate shoes',
      'trail shoes',
    ],
    outfitRoles: ['shoes'],
  },

  // --- Accessories ----------------------------------------------------------
  {
    id: 'bag',
    label: 'Bag',
    slot: 'accessories',
    subtypes: ['tote', 'crossbody', 'clutch', 'backpack', 'sling'],
    outfitRoles: ['bag'],
  },
  {
    id: 'accessory',
    label: 'Accessory',
    slot: 'accessories',
    subtypes: ['scarf', 'belt', 'hat', 'cap', 'jewellery', 'sunglasses', 'headwear'],
    outfitRoles: ['accessory'],
  },
];

const BY_ID = new Map(GARMENT_CATEGORIES.map((category) => [category.id, category]));

export function categoryById(id: string): GarmentCategory | undefined {
  return BY_ID.get(id);
}

export function slotFor(categoryId: string): Slot | undefined {
  return BY_ID.get(categoryId)?.slot;
}

export function categoriesInSlot(slot: Slot): readonly GarmentCategory[] {
  return GARMENT_CATEGORIES.filter((category) => category.slot === slot);
}

/**
 * The closed label set the vision model may return when categorising an upload.
 *
 * Closed on purpose: an open-ended "what is this garment" prompt returns "top",
 * "shirt", "button-down" and "oxford" for one photograph across four runs, and the
 * wardrobe ends up with four categories that are the same thing. The model picks
 * from this list or returns `unknown`.
 */
export const CLASSIFICATION_LABELS: readonly string[] = GARMENT_CATEGORIES.map(
  (category) => category.id,
);

/**
 * Regional garments keep their own identity.
 *
 * A broad "traditional" bucket is not good enough: a kanga is a named cloth that can
 * become several different garments, and flattening that loses the distinction
 * between the textile and the thing made from it. These carry local aliases so a
 * user's own word for their clothing finds it.
 */
export interface RegionalGarment {
  id: string;
  label: string;
  aliases: readonly string[];
  /** Whether this names a textile, a garment, or an ensemble of named pieces. */
  kind: 'textile' | 'garment' | 'ensemble';
  note: string;
  slot?: Slot;
}

export const REGIONAL_GARMENTS: readonly RegionalGarment[] = [
  {
    id: 'kitenge',
    label: 'Kitenge',
    aliases: ['chitenge', 'ankara'],
    kind: 'textile',
    note: 'A printed textile family. Becomes a shirt, dress, blazer or wrap. Record which.',
  },
  {
    id: 'kanga',
    label: 'Kanga',
    aliases: ['khanga', 'leso'],
    kind: 'textile',
    note: 'Named cloth, often carrying a printed message. Distinguish a draped wrapper from a sewn garment.',
  },
  {
    id: 'kikoi',
    label: 'Kikoi',
    aliases: ['kikoy'],
    kind: 'textile',
    note: 'Woven rectangular cloth. Distinguish wrap, trousers, skirt and towel uses.',
  },
  {
    id: 'kanzu',
    label: 'Kanzu',
    aliases: [],
    kind: 'garment',
    note: 'A named long robe with regional variants.',
    slot: 'tops',
  },
  {
    id: 'dera',
    label: 'Dera',
    aliases: [],
    kind: 'garment',
    note: 'A loose dress. Record actual length, sleeves and opacity. "Free size" still needs measurements.',
    slot: 'tops',
  },
  {
    id: 'abaya',
    label: 'Abaya',
    aliases: [],
    kind: 'garment',
    note: 'Long outer garment. The clothes underneath remain separate items.',
    slot: 'outerwear',
  },
  {
    id: 'kurta',
    label: 'Kurta',
    aliases: ['kurti'],
    kind: 'garment',
    note: 'Tunic family. Store actual length and cut rather than assuming.',
    slot: 'tops',
  },
  {
    id: 'sari',
    label: 'Sari',
    aliases: ['saree'],
    kind: 'garment',
    note: 'Draped garment with many fabrics and draping traditions. No single drape is universal.',
  },
  {
    id: 'agbada',
    label: 'Agbada',
    aliases: [],
    kind: 'ensemble',
    note: 'An ensemble: outer agbada, inner buba, sokoto trousers, each separately identifiable.',
  },
];
