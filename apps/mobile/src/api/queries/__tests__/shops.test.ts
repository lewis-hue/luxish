/**
 * What the screen says when there are no shops to show.
 *
 * Four different reasons produce an empty list and they are not
 * interchangeable. "No clothes shops listed near you" is a fact
 * about a neighbourhood; "the directory is not answering" is a fact
 * about a server. Telling somebody the first when the second is true
 * is the failure these cover.
 */

import { howFar, shopsNote, type NearbyShops } from '@/api/queries/shops';

function result(over: Partial<NearbyShops> = {}): NearbyShops {
  return {
    items: [],
    reachable: true,
    attribution: 'Shop locations © OpenStreetMap contributors',
    note: null,
    ...over,
  };
}

describe('shopsNote', () => {
  it('offers the permission rather than an error', () => {
    expect(shopsNote('needsPermission', null)).toContain('Allow location');
  });

  it('points at the setting when the consent is missing', () => {
    expect(shopsNote('needsConsent', null)).toContain('Settings');
  });

  it('says it could not place them', () => {
    expect(shopsNote('noPosition', null)).toContain('where you are');
  });

  it('distinguishes an unreachable directory from an empty one', () => {
    // **The distinction that matters.**
    const broken = shopsNote(null, result({ reachable: false }));
    const empty = shopsNote(null, result({ reachable: true }));
    expect(broken).not.toEqual(empty);
    expect(broken).toContain('not answering');
    expect(empty).toContain('No clothes shops');
  });

  it('prefers the note the server sent', () => {
    expect(
      shopsNote(null, result({ reachable: false, note: 'Try later.' })),
    ).toBe('Try later.');
  });

  it('says nothing when there is something to show', () => {
    expect(
      shopsNote(
        null,
        result({
          items: [
            {
              name: 'Bata',
              kind: 'shoes',
              latitude: 0,
              longitude: 0,
              distanceM: 400,
              brand: null,
              openingHours: null,
            },
          ],
        }),
      ),
    ).toBeNull();
  });
});

describe('howFar', () => {
  it('rounds metres to something worth reading', () => {
    // Nobody needs "417 m" from a coordinate rounded to a kilometre.
    expect(howFar(417)).toBe('400 m');
    expect(howFar(980)).toBe('1000 m');
  });

  it('switches to kilometres, with a decimal while it helps', () => {
    expect(howFar(2721)).toBe('2.7 km');
    expect(howFar(14200)).toBe('14 km');
  });

  it('says nothing when the distance is unknown', () => {
    expect(howFar(null)).toBe('');
  });
});
