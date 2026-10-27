/**
 * The taxonomy's load-bearing properties.
 *
 * Each test here corresponds to a claim in the fashion reference that, if violated,
 * produces visibly wrong advice rather than a subtle inaccuracy.
 */

import {
  AESTHETICS,
  CLASSIFICATION_LABELS,
  DRESS_CODES,
  GARMENT_CATEGORIES,
  REGIONAL_GARMENTS,
  SLOTS,
  aestheticById,
  categoryById,
  dressCodeById,
  explainAesthetic,
  isForbiddenInference,
  needsClarification,
  piecesBySlot,
  resolveAestheticSearch,
  slotFor,
  type OutfitPiece,
} from '@/features/taxonomy';

describe('dimensions are independent', () => {
  it('lets one outfit carry several aesthetics at once', () => {
    // A navy trouser suit is plausibly classic, elegant, minimalist and preppy.
    // A single-label model would have to pick, and the pick would be arguable.
    const suit = ['classic', 'elegant', 'minimalist', 'preppy'];
    for (const id of suit) expect(aestheticById(id)).toBeDefined();
  });

  it('keeps dress code separate from aesthetic', () => {
    // A minimalist outfit can be casual or black tie. If these shared a field,
    // that sentence could not be represented.
    const aestheticIds = new Set(AESTHETICS.map((a) => a.id));
    for (const code of DRESS_CODES) {
      expect(aestheticIds.has(code.id)).toBe(false);
    }
  });

  it('never stores an aesthetic on a garment category', () => {
    // The same white shirt is classic, business formal, streetwear or bohemian
    // depending only on what it is worn with.
    for (const category of GARMENT_CATEGORIES) {
      expect(category).not.toHaveProperty('aesthetic');
      expect(category).not.toHaveProperty('aesthetics');
    }
  });
});

describe('aesthetics', () => {
  it('gives every aesthetic a definition and at least two cues', () => {
    // A category a reviewer cannot apply consistently is not a category.
    for (const aesthetic of AESTHETICS) {
      expect(aesthetic.definition.length).toBeGreaterThan(20);
      expect(aesthetic.cues.length).toBeGreaterThanOrEqual(2);
    }
  });

  it('names the neighbours that are genuinely confusable', () => {
    // Annotation disagreement concentrates on these pairs, so they are recorded.
    expect(aestheticById('athleisure')?.confusableWith).toContain('sporty');
    expect(aestheticById('elegant')?.confusableWith).toContain('minimalist');
  });

  it('keeps confusableWith pointing at aesthetics that exist', () => {
    for (const aesthetic of AESTHETICS) {
      for (const neighbour of aesthetic.confusableWith ?? []) {
        expect(aestheticById(neighbour)).toBeDefined();
      }
    }
  });

  it('resolves marketing terms to stable categories', () => {
    expect(resolveAestheticSearch('quiet luxury').map((a) => a.id)).toEqual([
      'classic',
      'minimalist',
    ]);
    expect(resolveAestheticSearch('gorpcore').map((a) => a.id)).toEqual(['outdoor']);
  });

  it('explains a label with the evidence that produced it', () => {
    const streetwear = aestheticById('streetwear')!;
    const explained = explainAesthetic(streetwear, [
      'graphic tee',
      'statement trainers',
      'relaxed proportions',
    ]);
    // An unexplained tag cannot be argued with; this one can.
    expect(explained).toContain('Streetwear');
    expect(explained).toContain('graphic tee');
  });

  it('returns nothing for an empty search rather than everything', () => {
    expect(resolveAestheticSearch('   ')).toEqual([]);
  });
});

describe('dress codes', () => {
  it('does not treat smart casual and business casual as the same thing', () => {
    // One is a polished informal look anywhere; the other answers to an employer.
    const smart = dressCodeById('smart_casual')!;
    const business = dressCodeById('business_casual')!;
    expect(smart.formalityRank).not.toBe(business.formalityRank);
    expect(business.requiresClarification).toBe(true);
    expect(business.settledBy).toContain('workplace');
  });

  it('does not treat cocktail and semi-formal as synonyms', () => {
    expect(dressCodeById('cocktail')!.formalityRank).not.toBe(
      dressCodeById('semi_formal')!.formalityRank,
    );
  });

  it('asks a question when "formal" is ambiguous', () => {
    const question = needsClarification('formal');
    expect(question).toContain('black tie');
    // Guessing between four materially different outcomes is worse than asking.
    expect(question).toContain('cocktail');
  });

  it('does not interrogate the user when the term is unambiguous', () => {
    expect(needsClarification('black tie')).toBeNull();
    expect(needsClarification('casual')).toBeNull();
  });

  it('orders formality without implying quality', () => {
    const ranks = DRESS_CODES.map((code) => code.formalityRank);
    expect([...ranks].sort((a, b) => a - b)).toEqual(ranks);
  });
});

describe('garments', () => {
  it('assigns every category to one of the five wardrobe slots', () => {
    for (const category of GARMENT_CATEGORIES) {
      expect(SLOTS).toContain(category.slot);
    }
  });

  it('treats a dress as neither a top nor a bottom', () => {
    // It fills torso and legs at once, which is why it needs its own role.
    expect(categoryById('dress')!.outfitRoles).toEqual(['dress']);
  });

  it('exposes a closed label set for classification', () => {
    // An open-ended prompt returns "top", "shirt", "button-down" and "oxford" for
    // one photo across four runs, and the wardrobe grows four names for one thing.
    expect(CLASSIFICATION_LABELS.length).toBe(GARMENT_CATEGORIES.length);
    for (const label of CLASSIFICATION_LABELS) {
      expect(categoryById(label)).toBeDefined();
    }
  });

  it('maps a category to its slot', () => {
    expect(slotFor('jeans')).toBe('bottoms');
    expect(slotFor('blazer')).toBe('outerwear');
    expect(slotFor('nonsense')).toBeUndefined();
  });
});

describe('regional garments keep their own identity', () => {
  it('distinguishes a textile from a garment made from it', () => {
    // A kanga is cloth that becomes several different garments; flattening that
    // loses the distinction entirely.
    expect(REGIONAL_GARMENTS.find((g) => g.id === 'kanga')!.kind).toBe('textile');
    expect(REGIONAL_GARMENTS.find((g) => g.id === 'kanzu')!.kind).toBe('garment');
    expect(REGIONAL_GARMENTS.find((g) => g.id === 'agbada')!.kind).toBe('ensemble');
  });

  it('keeps local aliases so a user’s own word finds their clothing', () => {
    const kanga = REGIONAL_GARMENTS.find((g) => g.id === 'kanga')!;
    expect(kanga.aliases).toContain('leso');
    expect(kanga.aliases).toContain('khanga');
  });
});

describe('inferences that must never be drawn', () => {
  it.each([
    'religion',
    'ethnicity',
    'income_bracket',
    'mental health',
    'subculture membership',
  ])('refuses to infer %s', (field) => {
    // A gothic outfit is clothing. It is not evidence about the wearer.
    expect(isForbiddenInference(field)).toBe(true);
  });

  it('still allows legitimate clothing attributes', () => {
    for (const field of ['colour', 'formality', 'sleeve_length', 'material']) {
      expect(isForbiddenInference(field)).toBe(false);
    }
  });
});

describe('outfit composition', () => {
  const piece = (id: string, slot: OutfitPiece['slot'], role: string): OutfitPiece => ({
    id,
    name: id,
    categoryId: id,
    slot,
    role,
    colour: null,
    owned: true,
  });

  it('groups pieces into a stable, readable order', () => {
    const groups = piecesBySlot([
      piece('trainers', 'shoes', 'shoes'),
      piece('tshirt', 'tops', 'top'),
      piece('jeans', 'bottoms', 'bottom'),
    ]);
    expect(groups.map((group) => group.slot)).toEqual(['tops', 'bottoms', 'shoes']);
  });

  it('omits slots with no pieces rather than showing empty headings', () => {
    const groups = piecesBySlot([piece('tshirt', 'tops', 'top')]);
    expect(groups).toHaveLength(1);
  });
});
