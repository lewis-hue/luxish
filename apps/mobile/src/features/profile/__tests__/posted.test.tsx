import { screen } from '@testing-library/react-native';

import { type MinePost } from '@/api/queries/posts';
import { asFit, PostedBadge } from '@/features/profile/posted';
import { renderWithProviders } from '@/test-support/render';

function post(over: Partial<MinePost> = {}): MinePost {
  return {
    id: 'p1',
    authorId: 'u1',
    authorName: 'You',
    caption: 'Linen in town',
    occasion: null,
    mediaAssetIds: ['a1'],
    items: [],
    publishedAt: '2026-11-01T10:00:00Z',
    saves: 3,
    savedByMe: false,
    state: 'published',
    visibility: 'public',
    coverRatio: 0.8,
    screenMode: null,
    screenNote: null,
    createdAt: '2026-11-01T10:00:00Z',
    ...over,
  };
}

describe('asFit', () => {
  it('carries the cover shape, so a tile is laid out before it loads', () => {
    // The whole reason the server sends it: without a shape the tile
    // opens at a guess and the column re-flows when the bytes land.
    expect(asFit(post({ coverRatio: 0.5625 })).coverRatio).toBe(0.5625);
  });

  it('passes an unmeasured cover through as unknown, not as a guess', () => {
    expect(asFit(post({ coverRatio: null })).coverRatio).toBeNull();
  });

  it('keeps the id a tile opens by', () => {
    const fit = asFit(post({ id: 'abc', mediaAssetIds: ['cover'] }));
    expect(fit.id).toBe('abc');
    expect(fit.mediaAssetIds).toEqual(['cover']);
  });
});

describe('PostedBadge', () => {
  it('says so when a fit is private', async () => {
    // On your own profile a private fit looks exactly like a public
    // one, which is the point - so the tile has to say which it is.
    await renderWithProviders(<PostedBadge post={post({ visibility: 'private' })} />);
    expect(screen.getByText('Private')).toBeTruthy();
  });

  it('says nothing about an ordinary published fit', async () => {
    await renderWithProviders(<PostedBadge post={post()} />);
    expect(screen.queryByText('Private')).toBeNull();
    expect(screen.queryByText('Held')).toBeNull();
  });

  it('distinguishes a held fit from one the author took private', async () => {
    // Two different things that both mean "nobody else sees this",
    // and an author who cannot tell them apart cannot act on either.
    await renderWithProviders(<PostedBadge post={post({ state: 'held' })} />);
    expect(screen.getByText('Held')).toBeTruthy();
  });

  it('calls the author’s own choice private even once the screen has passed it', async () => {
    await renderWithProviders(
      <PostedBadge post={post({ state: 'published', visibility: 'private' })} />,
    );
    expect(screen.getByText('Private')).toBeTruthy();
  });
});
