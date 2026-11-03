/**
 * Ordering the Discover shelves from a stated taste.
 *
 * The smallest useful thing a taste profile does, and the one with a quiet
 * failure: a bare `indexOf` returns -1 for a lens the order does not mention,
 * which sorts it to the *front*. Add a lens on the server and not the client,
 * or the other way round, and the layout silently reshuffles instead of
 * ignoring the one it does not know.
 */

import {
  orderCollections,
  orderShelves,
  DEFAULT_LENS_ORDER,
  type Lens,
} from '@/api/queries/taste';

const SHELVES = [
  { id: 'occasion' as Lens, title: 'Where you are going' },
  { id: 'aesthetic' as Lens, title: 'The look' },
  { id: 'formula' as Lens, title: 'How to wear what you own' },
];

describe('orderShelves', () => {
  it('leaves the shelves alone when nothing has been said', () => {
    expect(orderShelves(SHELVES, undefined).map((s) => s.id)).toEqual([
      'occasion',
      'aesthetic',
      'formula',
    ]);
    expect(orderShelves(SHELVES, []).map((s) => s.id)).toEqual([
      'occasion',
      'aesthetic',
      'formula',
    ]);
  });

  it('leads with the lens the stated goal implies', () => {
    expect(
      orderShelves(SHELVES, ['formula', 'occasion', 'aesthetic']).map((s) => s.id),
    ).toEqual(['formula', 'occasion', 'aesthetic']);
  });

  it('keeps every shelf', () => {
    // Leading one must not drop the others, or answering one question would
    // remove two thirds of Discover.
    const ordered = orderShelves(SHELVES, ['aesthetic', 'occasion', 'formula']);
    expect(ordered).toHaveLength(SHELVES.length);
    expect(new Set(ordered.map((s) => s.id))).toEqual(
      new Set(SHELVES.map((s) => s.id)),
    );
  });

  it('does not promote a shelf the order never mentions', () => {
    // The -1 bug. A partial order must leave the unmentioned shelf where it
    // was, at the back, rather than sorting it above everything.
    const ordered = orderShelves(SHELVES, ['aesthetic'] as Lens[]);
    expect(ordered.map((s) => s.id)).toEqual(['aesthetic', 'occasion', 'formula']);
  });

  it('keeps unmentioned shelves in their original relative order', () => {
    const ordered = orderShelves(SHELVES, ['formula'] as Lens[]);
    expect(ordered.map((s) => s.id)).toEqual(['formula', 'occasion', 'aesthetic']);
  });

  it('matches the default the server sends when nothing is stated', () => {
    expect(orderShelves(SHELVES, DEFAULT_LENS_ORDER).map((s) => s.id)).toEqual([
      'occasion',
      'aesthetic',
      'formula',
    ]);
  });
});

describe('orderCollections', () => {
  const COLLECTIONS = [
    { id: 'capsule' },
    { id: 'denim' },
    { id: 'tailoring' },
    { id: 'layering' },
  ];

  it('leads with what the profile ranks first', () => {
    expect(
      orderCollections(COLLECTIONS, ['layering', 'denim']).map((c) => c.id),
    ).toEqual(['layering', 'denim', 'capsule', 'tailoring']);
  });

  it('keeps the collections the profile never mentions', () => {
    // A shelf that drops what the profile did not rank gets *shorter* the
    // more we know about somebody, which is exactly backwards.
    const ordered = orderCollections(COLLECTIONS, ['denim']);
    expect(ordered).toHaveLength(COLLECTIONS.length);
    expect(ordered[0].id).toBe('denim');
  });

  it('leaves everything alone when there is no profile yet', () => {
    expect(orderCollections(COLLECTIONS, undefined).map((c) => c.id)).toEqual([
      'capsule',
      'denim',
      'tailoring',
      'layering',
    ]);
  });

  it('does not promote an unranked collection to the front', () => {
    // The -1 hazard again, in the second place it appears.
    expect(orderCollections(COLLECTIONS, ['tailoring']).map((c) => c.id)).toEqual([
      'tailoring',
      'capsule',
      'denim',
      'layering',
    ]);
  });
});
