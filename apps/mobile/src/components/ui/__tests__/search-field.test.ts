/**
 * What search has to do to be worth having.
 *
 * A fashion wardrobe is full of compound words and the names people give
 * garments rarely match the words they later search for: someone types
 * "denim" looking for the jeans they named "work trousers". These pin the
 * behaviours that make that work, and the one that would make it annoying.
 */

import { matchesQuery } from '@/components/ui/search-field';

describe('matchesQuery', () => {
  it('matches nothing in particular when the query is empty', () => {
    // An empty field is not a filter. Returning false here would show an
    // empty grid until the first keystroke.
    expect(matchesQuery('', 'linen shirt')).toBe(true);
    expect(matchesQuery('   ', 'linen shirt')).toBe(true);
  });

  it('ignores the order the terms were typed in', () => {
    expect(matchesQuery('linen shirt', 'Shirt, linen')).toBe(true);
    expect(matchesQuery('shirt linen', 'Shirt, linen')).toBe(true);
  });

  it('requires every term, not any of them', () => {
    // "black boots" must not return every black thing and every boot.
    expect(matchesQuery('black boots', 'black leather boots')).toBe(true);
    expect(matchesQuery('black boots', 'black beanie')).toBe(false);
  });

  it('matches inside compounds, because garment words are full of them', () => {
    expect(matchesQuery('neck', 'white crewneck sweatshirt')).toBe(true);
  });

  it('is case and whitespace insensitive', () => {
    expect(matchesQuery('  LINEN   Shirt ', 'linen shirt')).toBe(true);
  });

  it('searches every field it is given, skipping the absent ones', () => {
    expect(matchesQuery('denim', 'work trousers', null, 'jeans', undefined, 'denim')).toBe(
      true,
    );
    expect(matchesQuery('silk', 'work trousers', null, 'jeans')).toBe(false);
  });
});
