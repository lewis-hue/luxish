import { wearCutPieces, dress } from '@/features/stylist/try-on';
import type { OutfitPiece } from '@/features/stylist/run';
import type { WardrobeEntry } from '@/features/wardrobe/store';

function piece(over: Partial<OutfitPiece> = {}): OutfitPiece {
  return {
    role: 'top',
    owned: true,
    garmentId: 'g1',
    name: 'White poplin shirt',
    category: 'shirt',
    ...over,
  };
}

function entry(over: Partial<WardrobeEntry> = {}): WardrobeEntry {
  return {
    id: 'local-1',
    serverId: 'g1',
    name: 'White poplin shirt',
    uri: 'file://cutout-1.png',
    isSample: false,
    ...over,
  } as unknown as WardrobeEntry;
}

describe('dress', () => {
  it('puts a garment the person owns on the figure', () => {
    expect(dress([piece()], [entry()])).toEqual([
      { id: 'g1', slot: 'tops', uri: 'file://cutout-1.png' },
    ]);
  });

  it('matches on the garment id, never on the name', () => {
    // Two black t-shirts have the same name and are different
    // garments. Dressing somebody in the wrong one is worse than
    // leaving the slot empty.
    const theirs = entry({ serverId: 'g2', uri: 'file://other.png' });
    expect(dress([piece({ garmentId: 'g1' })], [theirs])).toEqual([]);
  });

  it('leaves out a piece the stylist said to go and buy', () => {
    // The picture is of their own wardrobe, so a shopping suggestion
    // is not in it.
    expect(dress([piece({ owned: false })], [entry()])).toEqual([]);
  });

  it('leaves out a garment with no cut-out yet', () => {
    // A piece whose background has not been removed would be a
    // rectangle of somebody's carpet laid over the figure.
    expect(dress([piece()], [entry({ uri: null })])).toEqual([]);
  });

  it('leaves out a category that sits in no slot', () => {
    expect(dress([piece({ category: 'not-a-category' })], [entry()])).toEqual(
      [],
    );
  });

  it('leaves out a piece with no garment behind it', () => {
    expect(dress([piece({ garmentId: null })], [entry()])).toEqual([]);
  });

  it('dresses a whole outfit, each piece into its own slot', () => {
    const pieces = [
      piece({ garmentId: 'top', category: 'shirt' }),
      piece({ garmentId: 'legs', category: 'jeans' }),
      piece({ garmentId: 'feet', category: 'shoes' }),
    ];
    const wardrobe = [
      entry({ serverId: 'top', uri: 'file://top.png' }),
      entry({ serverId: 'legs', uri: 'file://legs.png' }),
      entry({ serverId: 'feet', uri: 'file://feet.png' }),
    ];
    expect(dress(pieces, wardrobe).map((worn) => worn.slot)).toEqual([
      'tops',
      'bottoms',
      'shoes',
    ]);
  });
});

describe('wearCutPieces', () => {
  const uris = { 'a-1': 'file:///tee.png', 'a-2': 'file:///jeans.png' };

  it('dresses the figure in the fit own garments', () => {
    // The clothes in the photograph, not a redrawing of them.
    const worn = wearCutPieces(
      [
        { mediaAssetId: 'a-2', category: 'jeans', position: 1 },
        { mediaAssetId: 'a-1', category: 'tshirt', position: 0 },
      ],
      uris,
    );
    expect(worn.map((piece) => piece.id)).toEqual(['a-1', 'a-2']);
  });

  it('keeps the described order rather than the order it was handed', () => {
    const worn = wearCutPieces(
      [
        { mediaAssetId: 'a-2', category: 'jeans', position: 5 },
        { mediaAssetId: 'a-1', category: 'tshirt', position: 2 },
      ],
      uris,
    );
    expect(worn[0].id).toBe('a-1');
  });

  it('leaves out a piece whose picture has not arrived', () => {
    const worn = wearCutPieces(
      [{ mediaAssetId: 'missing', category: 'tshirt', position: 0 }],
      uris,
    );
    expect(worn).toEqual([]);
  });

  it('leaves out a piece that maps to no slot', () => {
    // `null`, and equally a category the taxonomy does not know.
    // A jumper drawn where the shoes go is worse than a figure
    // wearing one thing less.
    const worn = wearCutPieces(
      [{ mediaAssetId: 'a-1', category: null, position: 0 }],
      uris,
    );
    expect(worn).toEqual([]);
  });

  it('answers with nothing when a fit has no cut pieces', () => {
    // The honest case for a fit nobody has read yet, and the one
    // where the screen offers the photoreal render instead.
    expect(wearCutPieces([], uris)).toEqual([]);
  });
});
