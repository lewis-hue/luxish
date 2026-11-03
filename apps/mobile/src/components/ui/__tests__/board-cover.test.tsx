/**
 * A board shows what is on it.
 *
 * This is the regression the screenshot work introduced and these
 * pin: a board holds published fits now, but the cover was still
 * looking up catalogue artwork from look ids nothing carries - so a
 * board with four pinned photographs rendered the word "Empty" and
 * the caption under it read "0 looks".
 */

import { screen } from '@testing-library/react-native';

import { BoardCover, type BoardFace } from '@/components/ui/board-cover';
import { renderWithProviders } from '@/test-support/render';

// The bytes are fetched and decrypted per asset; the composition is
// what this file is about.
jest.mock('@/api/queries/post-media', () => ({
  usePostImage: (asset: string | null) => ({
    data: asset ? `file:///cache/${asset}.webp` : null,
  }),
}));

function faces(count: number): BoardFace[] {
  return Array.from({ length: count }, (_, at) => ({
    postId: `fit-${at}`,
    coverAssetId: `asset-${at}`,
  }));
}

function tree(): string {
  return JSON.stringify(screen.toJSON());
}

describe('a board cover', () => {
  it('says Empty only when the board is empty', async () => {
    await renderWithProviders(<BoardCover faces={[]} />);
    expect(screen.getByText('Empty')).toBeTruthy();
  });

  it('does not say Empty when fits are pinned to it', async () => {
    // The bug, exactly.
    await renderWithProviders(<BoardCover faces={faces(4)} />);
    expect(screen.queryByText('Empty')).toBeNull();
  });

  it('gives a single pin the whole frame', async () => {
    await renderWithProviders(<BoardCover faces={faces(1)} />);
    expect(tree()).toContain('asset-0');
    expect(tree()).not.toContain('asset-1');
  });

  it('shows at most four, so a cover stays readable', async () => {
    await renderWithProviders(<BoardCover faces={faces(9)} />);
    expect(tree()).toContain('asset-3');
    expect(tree()).not.toContain('asset-4');
  });

  it('gives the first pin the larger half once there are others', async () => {
    // Four equal squares is a component library's idea of a collage.
    await renderWithProviders(<BoardCover faces={faces(3)} />);
    expect(tree()).toContain('"flex":1.2');
  });

  it('holds its shape where a fit has no picture to show', async () => {
    // Taken down since it was pinned. A tinted gap, not a hole, and
    // nobody is told their board is broken.
    await renderWithProviders(
      <BoardCover
        faces={[
          { postId: 'fit-0', coverAssetId: null },
          { postId: 'fit-1', coverAssetId: 'asset-1' },
        ]}
      />,
    );
    expect(screen.queryByText('Empty')).toBeNull();
    expect(tree()).toContain('asset-1');
  });

  it('tells each face which fit it is drawing', async () => {
    // Covers are drawn in a recycling grid of boards.
    await renderWithProviders(<BoardCover faces={faces(2)} />);
    expect(tree()).toContain('"recyclingKey":"fit-0"');
  });

  it('is not announced face by face', async () => {
    // The board's name and count beside it are the label.
    await renderWithProviders(<BoardCover faces={faces(2)} />);
    expect(tree()).toContain('"accessible":false');
  });
});
