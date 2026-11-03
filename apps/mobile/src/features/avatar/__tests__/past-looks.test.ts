import type { Render } from '@/api/queries/avatar';
import { pastLooks } from '@/features/avatar/past-looks';

function render(over: Partial<Render> = {}): Render {
  return {
    id: 'r1',
    kind: 'try_on',
    state: 'ready',
    assetId: 'a1',
    outfit: 'white shirt, indigo jeans',
    pieces: [],
    error: null,
    uri: 'file://look.png',
    ...over,
  };
}

describe('pastLooks', () => {
  it('recalls a look drawn earlier', () => {
    // The whole point: a render is a billed picture somebody waited
    // half a minute for, and it used to vanish on the next question.
    expect(pastLooks([render()], null)).toHaveLength(1);
  });

  it('leaves out the one already on screen above it', () => {
    expect(pastLooks([render({ id: 'shown' })], 'shown')).toEqual([]);
  });

  it('leaves out the base avatar, which is not a look', () => {
    expect(pastLooks([render({ kind: 'base' })], null)).toEqual([]);
  });

  it('leaves out one still being drawn', () => {
    expect(pastLooks([render({ state: 'running', uri: null })], null)).toEqual(
      [],
    );
  });

  it('leaves out one that failed', () => {
    expect(
      pastLooks([render({ state: 'failed', uri: null, error: 'no' })], null),
    ).toEqual([]);
  });

  it('leaves out one whose picture has not downloaded', () => {
    // A tile with no image is a grey box claiming to be a look.
    expect(pastLooks([render({ uri: null })], null)).toEqual([]);
  });

  it('keeps the strip to a recall rather than an archive', () => {
    const many = Array.from({ length: 30 }, (_, at) =>
      render({ id: `r${at}` }),
    );
    expect(pastLooks(many, null)).toHaveLength(12);
  });

  it('keeps the order it was given, which is newest first', () => {
    const looks = [render({ id: 'new' }), render({ id: 'old' })];
    expect(pastLooks(looks, null).map((look) => look.id)).toEqual([
      'new',
      'old',
    ]);
  });
});
