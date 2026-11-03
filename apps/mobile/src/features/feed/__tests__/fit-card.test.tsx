/**
 * The pin is a tile, and on Discover it is a tile with a menu.
 *
 * Asked for exactly: "the pins shown should not show likes comments etc
 * and the three dots. They should just be tiles... however in image 3
 * that is on the discovery tab, the pins can retain the three dots".
 * Two screens, one component, and the only difference is whether a
 * menu was handed to it - which is easy to undo by adding a count row
 * back "just for the feed".
 */

import { act, screen } from '@testing-library/react-native';

import { type FeedFit } from '@/api/queries/discover-feed';
import { FitCard } from '@/features/feed/fit-card';
import { SHAPE } from '@/features/feed/shape';
import { renderWithProviders } from '@/test-support/render';

// The photograph itself is fetched and decrypted per asset; what this
// file is about is the frame around it, so the bytes are stood in for.
jest.mock('@/api/queries/post-media', () => ({
  usePostImage: (asset: string) => ({
    data: asset ? `file:///cache/${asset}.webp` : null,
  }),
}));

const FIT: FeedFit = {
  id: 'fit-1',
  authorId: 'person-1',
  authorName: 'Imani',
  caption: 'Linen, before the heat broke',
  captionIsDescribed: false,
  mediaAssetIds: ['asset-1'],
  coverRatio: 0.72,
  tags: ['linen'],
  groups: [],
  reactions: 48,
  saves: 1632,
  comments: 7,
  myReaction: null,
  savedByMe: false,
  publishedAt: '2026-05-01T09:00:00Z',
};

function tree(): string {
  return JSON.stringify(screen.toJSON());
}

/**
 * Hand the tile the dimensions its photograph decoded to.
 *
 * Walked off `screen.root` rather than queried: RNTL 14 exposes no
 * find-by-type, and `onLoad` is a prop rather than anything a user-facing
 * query can reach.
 */
async function decodesAt(width: number, height: number): Promise<void> {
  const nodes = [screen.root];
  while (nodes.length) {
    const node = nodes.shift();
    if (!node) continue;
    const onLoad = node.props?.onLoad;
    if (typeof onLoad === 'function') {
      // The node carrying the handler is expo-image's native adapter, so
      // it is called the way the platform calls it: the payload arrives
      // under `nativeEvent` and the component unwraps it.
      await act(async () => {
        onLoad({ nativeEvent: { source: { width, height } } });
      });
      return;
    }
    nodes.push(...(node.children ?? []).filter((c) => typeof c !== 'string'));
  }
  throw new Error('no picture on this tile to load');
}

describe('a pin on a board', () => {
  it('shows no counts under the photograph', async () => {
    // The numbers are on the fit itself. A board of a hundred and
    // twenty tiles with five controls each reads as a dashboard.
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    for (const count of ['48', '1.6K', '1632', '7']) {
      expect(screen.queryByText(count)).toBeNull();
    }
  });

  it('shows no menu where none was given', async () => {
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    expect(screen.queryByLabelText("More for Imani's fit")).toBeNull();
    expect(tree()).not.toContain('ellipsis');
  });

  it('does not put the author under the tile either', async () => {
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    expect(screen.queryByText('Imani')).toBeNull();
  });

  it('is still one button that opens the fit', async () => {
    // Stripping the chrome must not strip the affordance: the whole
    // tile is the target, and it says whose it is to a screen reader.
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    expect(
      screen.getByLabelText('Imani. Linen, before the heat broke'),
    ).toBeTruthy();
  });

  it('says it is a fit when there is no caption to read', async () => {
    await renderWithProviders(
      <FitCard fit={{ ...FIT, caption: null }} width={180} />,
    );
    expect(screen.getByLabelText('Imani. A fit.')).toBeTruthy();
  });
});

describe('a pin on Discover', () => {
  it('keeps the three dots, below the tile', async () => {
    await renderWithProviders(
      <FitCard fit={FIT} width={180} onMore={() => {}} />,
    );
    expect(screen.getByLabelText("More for Imani's fit")).toBeTruthy();
  });

  it('still shows no counts beside them', async () => {
    // The dots came back; the dashboard must not come back with them.
    await renderWithProviders(
      <FitCard fit={FIT} width={180} onMore={() => {}} />,
    );
    for (const count of ['48', '1.6K', '7']) {
      expect(screen.queryByText(count)).toBeNull();
    }
  });
});

describe('the shape of a tile', () => {
  it('lays out at the shape the server sent, before any picture loads', async () => {
    // What stops the column re-flowing as photographs decode, which is
    // the jump people see scrolling up and down a board.
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    expect(tree()).toContain('"aspectRatio":0.72');
  });

  it('clamps a photograph too tall to sit in a column', async () => {
    // One 9:21 frame would push everything beside it a screen down.
    //
    // The floor is `SHAPE.tallest`, shared with the hero on the fit's
    // own page. It was 0.45 here and unbounded there, which is how a
    // studio render ended up a different shape in the grid from the
    // page it opened.
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: 0.1 }} width={180} />,
    );
    expect(tree()).toContain(`"aspectRatio":${SHAPE.tallest}`);
    expect(tree()).not.toContain('"aspectRatio":0.1');
  });

  it('gives a studio render the same shape as a photograph', async () => {
    // The one that prompted this: generated full-length figures come
    // back near 0.47, tall enough that the old bounds drew them
    // narrower than everything around them.
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: 0.47 }} width={180} />,
    );
    expect(tree()).toContain(`"aspectRatio":${SHAPE.tallest}`);
  });

  it('clamps a panorama the same way', async () => {
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: 3 }} width={180} />,
    );
    expect(tree()).toContain('"aspectRatio":1.45');
  });

  it('guesses 3:4 only when the server knows no shape', async () => {
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: null, mediaAssetIds: ['b'] }} width={180} />,
    );
    expect(tree()).toContain('"aspectRatio":0.75');
  });

  it('does not resize when the photograph decodes', async () => {
    // The scroll glitch, pinned. The server rounds `cover_ratio` to four
    // decimals, so 736x1292 arrives as 0.5697 and the file decodes to
    // 0.5696594427244582. Taking the decoded quotient changed the tile's
    // height the instant its picture loaded - and in a masonry list every
    // tile below a changed one moves with it.
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: 0.5697 }} width={180} />,
    );
    expect(tree()).toContain('"aspectRatio":0.5697');

    await decodesAt(736, 1292);

    expect(tree()).toContain('"aspectRatio":0.5697');
    expect(tree()).not.toContain('0.5696594427244582');
  });

  it('still measures a photograph the server could not describe', async () => {
    // An asset uploaded before dimensions were recorded. Here the decode
    // is the only source of the shape, so it must be used.
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: null }} width={180} />,
    );
    expect(tree()).toContain('"aspectRatio":0.75');

    await decodesAt(800, 1000);

    expect(tree()).toContain('"aspectRatio":0.8');
  });

  it('ignores a measured difference too small to see', async () => {
    // A re-layout moves every tile below this one, so it has to be worth
    // something. A thousandth of a ratio is a fraction of a point of
    // height on a 180-point column.
    await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: null, mediaAssetIds: ['c'] }} width={180} />,
    );
    await decodesAt(7501, 10000);
    expect(tree()).toContain('"aspectRatio":0.75');
  });

  it('shows an already-cached photograph instantly, with no fade', async () => {
    // Scrolling back up a board re-faded every tile that was already on
    // disk, which reads as the grid flickering rather than as anything
    // appearing. expo-image names this: without `skipOnCacheHit` a
    // cached picture "re-animates on every mount, tab change, or scroll
    // back into view". The fade is only for a first arrival over the
    // network.
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    expect(tree()).toContain('"skipOnCacheHit":"all"');
    // Not a bare duration, which is what replays the fade every time.
    expect(tree()).not.toMatch(/"transition":\d/);
  });

  it('takes the new shape when its cell is recycled', async () => {
    // The lurch, pinned. This list reuses cells, so one component
    // instance shows many fits. A ratio held in state keeps whatever
    // the cell held before - `useState`'s initialiser runs once per
    // instance, not once per fit - and the column re-flows around
    // tiles claiming the wrong height.
    const view = await renderWithProviders(
      <FitCard fit={{ ...FIT, coverRatio: 0.5 }} width={180} />,
    );
    expect(JSON.stringify(view.toJSON())).toContain('"aspectRatio":0.5');

    // The same instance, a different fit: exactly what recycling does.
    await view.rerender(
      <FitCard
        fit={{ ...FIT, id: 'fit-2', coverRatio: 1.2, mediaAssetIds: ['asset-2'] }}
        width={180}
      />,
    );
    const after = JSON.stringify(view.toJSON());
    expect(after).toContain('"aspectRatio":1.2');
    expect(after).not.toContain('"aspectRatio":0.5');
  });

  it('does not carry a measured shape onto the next fit', async () => {
    // The same trap for the covers the server cannot describe: what
    // this device measured belongs to the asset it measured, not to
    // whichever fit the cell shows next.
    const view = await renderWithProviders(
      <FitCard
        fit={{ ...FIT, coverRatio: null, mediaAssetIds: ['measured-1'] }}
        width={180}
      />,
    );
    await decodesAt(900, 1000);
    expect(JSON.stringify(view.toJSON())).toContain('"aspectRatio":0.9');

    await view.rerender(
      <FitCard
        fit={{ ...FIT, id: 'fit-3', coverRatio: null, mediaAssetIds: ['measured-2'] }}
        width={180}
      />,
    );
    // Back to the guess for a cover nothing knows about, not 0.9.
    expect(JSON.stringify(view.toJSON())).toContain('"aspectRatio":0.75');
  });

  it('tells a recycled view which fit it is showing', async () => {
    // Without this a tile keeps the previous photograph on screen until
    // the new one loads - the flash on a fast scroll back.
    await renderWithProviders(<FitCard fit={FIT} width={180} />);
    expect(tree()).toContain('"recyclingKey":"fit-1"');
  });
});
