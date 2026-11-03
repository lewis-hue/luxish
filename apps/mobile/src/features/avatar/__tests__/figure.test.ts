import {
  LAYER_ORDER,
  figureKeyFor,
  inLayerOrder,
  type WornPiece,
} from '@/features/avatar/figure';

function worn(slot: WornPiece['slot'], id = slot): WornPiece {
  return { id, slot, uri: `file://${id}.png` };
}

describe('inLayerOrder', () => {
  it('puts a coat over a shirt however the outfit arrived', () => {
    // The order must not depend on whichever order the stylist
    // happened to answer in: a coat behind a shirt is not a look.
    const shuffled = [worn('outerwear'), worn('shoes'), worn('tops'), worn('bottoms')];
    expect(inLayerOrder(shuffled).map((piece) => piece.slot)).toEqual([
      'bottoms',
      'tops',
      'shoes',
      'outerwear',
    ]);
  });

  it('hangs a bag outside the coat', () => {
    expect(LAYER_ORDER.indexOf('accessories')).toBeGreaterThan(
      LAYER_ORDER.indexOf('outerwear'),
    );
  });

  it('dresses from the bottom up, the way a person does', () => {
    expect(LAYER_ORDER.indexOf('bottoms')).toBeLessThan(
      LAYER_ORDER.indexOf('tops'),
    );
  });

  it('drops a piece with no picture rather than drawing a gap', () => {
    const pieces = [worn('tops'), { id: 'x', slot: 'bottoms' as const, uri: null }];
    expect(inLayerOrder(pieces).map((piece) => piece.id)).toEqual(['tops']);
  });

  it('leaves the caller’s array alone', () => {
    // It sorts a copy: the outfit is rendered elsewhere too, and a
    // list that reorders itself under the rows showing it is a bug
    // nobody would look for here.
    const pieces = [worn('outerwear'), worn('bottoms')];
    inLayerOrder(pieces);
    expect(pieces.map((piece) => piece.slot)).toEqual(['outerwear', 'bottoms']);
  });
});

describe('figureKeyFor', () => {
  // Asserted on the key rather than the asset: `jest-expo` resolves
  // every image `require` to the same number, so comparing the
  // modules themselves would pass whatever this returned.
  it('stands womenswear on its own figure', () => {
    expect(figureKeyFor('womenswear')).toBe('womenswear');
  });

  it('falls back to one figure rather than none', () => {
    // Nobody is asked their gender to use the stylist, so unspecified
    // still has to draw something.
    expect(figureKeyFor('unspecified')).toBe('menswear');
    expect(figureKeyFor('unisex')).toBe('menswear');
  });
});
