/**
 * The studio's one shape option, as far as the wire.
 *
 * Twice now a field has been added to the request schema and quietly
 * dropped on its way out of this client - once on each of these two
 * hooks - and the symptom is the worst kind: the box is checked, the
 * request succeeds, and the picture comes back the other way round
 * with nothing anywhere saying why. A unit test on the body is the
 * only thing that catches it, because a type does not: both bodies
 * are cast through `as never` to satisfy the generated client.
 */

import { renderHook, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';

import { api } from '@/api/client';
import { useShootAsset, useShootEachItem } from '@/api/queries/garment-studio';

jest.mock('@/api/client', () => ({
  api: { POST: jest.fn() },
  API_BASE_URL: 'http://example.invalid',
}));

const post = api.POST as unknown as jest.Mock;

function wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The body the hook actually sent, from the single recorded call. */
function sentBody(): Record<string, unknown> {
  expect(post).toHaveBeenCalledTimes(1);
  return post.mock.calls[0][1].body as Record<string, unknown>;
}

const ASK = {
  mediaAssetId: '11111111-1111-4111-8111-111111111111',
  treatment: 'packshot',
};

beforeEach(() => {
  post.mockReset();
});

describe('useShootAsset', () => {
  it('carries a request for a wide frame', async () => {
    post.mockResolvedValue({
      data: { id: 'a', treatment: 'packshot', state: 'queued' },
      error: null,
    });

    const { result } = await renderHook(() => useShootAsset(), { wrapper });
    result.current.mutate({ ...ASK, landscape: true });

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(sentBody().landscape).toBe(true);
  });

  it('asks for upright when nobody said otherwise', async () => {
    post.mockResolvedValue({
      data: { id: 'a', treatment: 'packshot', state: 'queued' },
      error: null,
    });

    const { result } = await renderHook(() => useShootAsset(), { wrapper });
    result.current.mutate(ASK);

    await waitFor(() => expect(post).toHaveBeenCalled());
    // Sent explicitly rather than omitted. The server defaults to
    // false either way, but a body that states it is a body somebody
    // reading a log can tell apart from one that forgot.
    expect(sentBody().landscape).toBe(false);
  });
});

describe('useShootEachItem', () => {
  it('carries the same option to every picture of the split', async () => {
    post.mockResolvedValue({ data: { job_id: 'j' }, error: null });

    const { result } = await renderHook(() => useShootEachItem(), { wrapper });
    result.current.mutate({ ...ASK, landscape: true });

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(sentBody().landscape).toBe(true);
  });
});
