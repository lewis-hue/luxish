/**
 * A search is never a dead end.
 *
 * The screen used to answer a query it could not match with one line
 * about hashtags and a button that emptied the box. That tells
 * somebody their search was wrong and leaves them to guess again, and
 * it described the search as a tag lookup when people and boards are
 * searched too.
 */
import type { Door } from '@/api/queries/explore';
import { MOST_REFINEMENTS, refinements } from '@/features/search/refine';

const door = (key: string, posts = 10): Door => ({
  kind: 'tag',
  key,
  label: key,
  posts,
  coverAssetId: `asset-${key}`,
});

describe('refinements', () => {
  it('puts tags related to what was typed first', () => {
    // They are the only ones that answer *this* search.
    const got = refinements({
      related: ['linen', 'summer'],
      popular: [door('denim'), door('boots')],
    });
    expect(got.map((d) => d.key)).toEqual(['linen', 'summer', 'denim', 'boots']);
  });

  it('falls back to what is busy when nothing is related', () => {
    // The gibberish case, which is the whole reason this exists: a
    // query that matched nothing has no related anything.
    const got = refinements({
      related: [],
      popular: [door('denim'), door('boots')],
    });
    expect(got.map((d) => d.key)).toEqual(['denim', 'boots']);
  });

  it('never offers back the thing that just failed', () => {
    // A row that re-runs the search which produced it is a loop.
    const got = refinements({
      related: ['linen'],
      popular: [door('linen'), door('denim')],
      exclude: 'linen',
    });
    expect(got.map((d) => d.key)).toEqual(['denim']);
  });

  it('ignores a hash and padding when excluding', () => {
    const got = refinements({ popular: [door('linen')], exclude: '  #Linen ' });
    expect(got).toEqual([]);
  });

  it('shows the same row only once', () => {
    // A related tag is very often also a popular one.
    const got = refinements({
      related: ['denim'],
      popular: [door('denim'), door('DENIM'), door('boots')],
    });
    expect(got.map((d) => d.key)).toEqual(['denim', 'boots']);
  });

  it('offers a handful, not a browse', () => {
    const got = refinements({
      popular: Array.from({ length: 30 }, (_, at) => door(`tag-${at}`)),
    });
    expect(got).toHaveLength(MOST_REFINEMENTS);
  });

  it('drops a blank rather than drawing an empty row', () => {
    const got = refinements({ related: ['', '   '], popular: [door('denim')] });
    expect(got.map((d) => d.key)).toEqual(['denim']);
  });

  it('answers with nothing when there is nothing to offer', () => {
    // The caller draws no heading in this case. A "Refine your
    // search" with no rows under it is worse than no heading.
    expect(refinements({})).toEqual([]);
    expect(refinements({ related: [], popular: [] })).toEqual([]);
  });

  it('keeps the cover that came with a popular door', () => {
    // It is what makes a row a place rather than a word.
    const [first] = refinements({ popular: [door('denim')] });
    expect(first.coverAssetId).toBe('asset-denim');
  });
});
