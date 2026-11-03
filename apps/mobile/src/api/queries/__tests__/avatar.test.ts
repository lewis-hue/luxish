/**
 * The instruction a try-on is driven by.
 *
 * A try-on is a billed image edit driven entirely by `outfitSentence`. An
 * empty or near-empty sentence does not fail loudly - it spends a model
 * call and returns the same figure in different clothes than the one
 * asked for, which reads as the feature not working rather than as a
 * missing description.
 *
 * It used to be asserted across every look in the catalogue as well. The
 * catalogue is gone; what is left is the phrasing, which is the part the
 * model actually reads.
 */

import { outfitSentence } from '@/api/queries/avatar';

describe('outfitSentence', () => {
  it('leads each piece with its colour', () => {
    expect(
      outfitSentence([
        { name: 'Trench coat', colour: 'camel' },
        { name: 'Wide-leg trousers', colour: 'ivory' },
      ]),
    ).toBe('camel trench coat, ivory wide-leg trousers');
  });

  it('does not repeat a colour the name already carries', () => {
    // "black black leather jacket" is the kind of phrasing that makes an image
    // model draw two jackets.
    expect(outfitSentence([{ name: 'Black leather jacket', colour: 'black' }])).toBe(
      'black leather jacket',
    );
  });

  it('names a piece with no colour', () => {
    expect(outfitSentence([{ name: 'Zip fleece', colour: null }])).toBe('zip fleece');
  });

  it('stops at six pieces, so the instruction stays an outfit', () => {
    const many = Array.from({ length: 10 }, (_, index) => ({
      name: `Piece ${index}`,
      colour: null,
    }));
    expect(outfitSentence(many).split(', ')).toHaveLength(6);
  });
});
