/**
 * The shape a fit's cover is, carried between screens.
 *
 * This exists for one symptom: opening a pin resized the picture while
 * somebody was looking at it. The fit screen sized its frame from a 3:4
 * guess until its own detail request returned, even though the tile that
 * was tapped already knew the answer.
 */

import { toFeedFit } from '@/api/queries/discover-feed';
import { forgetShapes, rememberShape, shapeFor } from '@/features/feed/shapes';

beforeEach(() => {
  forgetShapes();
});

describe('remembering a cover shape', () => {
  it('hands back what it was told', () => {
    rememberShape('fit-1', 0.5697);
    expect(shapeFor('fit-1')).toBe(0.5697);
  });

  it('knows nothing about a fit it has not seen', () => {
    // The caller falls back to its own guess, which is why this returns
    // undefined rather than a number that would look authoritative.
    expect(shapeFor('never-seen')).toBeUndefined();
  });

  it('ignores a shape the server could not supply', () => {
    rememberShape('fit-2', null);
    expect(shapeFor('fit-2')).toBeUndefined();
  });

  it('ignores a value that could not be a shape', () => {
    // A zero or a negative would be applied as an aspectRatio and take
    // the frame to nothing, which is worse than the guess it replaced.
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      rememberShape('fit-3', bad);
      expect(shapeFor('fit-3')).toBeUndefined();
    }
  });

  it('ignores an empty id', () => {
    rememberShape('', 0.75);
    expect(shapeFor('')).toBeUndefined();
  });

  it('takes the newest answer for a fit', () => {
    rememberShape('fit-4', 0.75);
    rememberShape('fit-4', 0.5);
    expect(shapeFor('fit-4')).toBe(0.5);
  });
});

describe('every screen showing a fit records its shape', () => {
  // The point of putting this in the mapper: a shape learned on any
  // screen is known on the next one, with no route parameters to thread
  // and no call site to forget.
  const wire = {
    id: 'fit-9',
    author_id: 'person-1',
    author_name: 'Imani',
    cover_ratio: 0.5697,
    media_asset_ids: ['asset-1'],
  };

  it('is recorded by mapping one off the wire', () => {
    expect(shapeFor('fit-9')).toBeUndefined();
    toFeedFit(wire);
    expect(shapeFor('fit-9')).toBe(0.5697);
  });

  it('records nothing for a fit the server could not measure', () => {
    toFeedFit({ ...wire, cover_ratio: null });
    expect(shapeFor('fit-9')).toBeUndefined();
  });

  it('still returns the fit it mapped', () => {
    // The recording is a side effect on a cache; it must not change what
    // the mapper is for.
    const fit = toFeedFit(wire);
    expect(fit.id).toBe('fit-9');
    expect(fit.coverRatio).toBe(0.5697);
    expect(fit.authorName).toBe('Imani');
  });
});
