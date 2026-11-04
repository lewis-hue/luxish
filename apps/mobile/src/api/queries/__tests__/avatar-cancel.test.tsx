/**
 * Stopping a render: the call, and the lists that have to be re-read.
 *
 * **There was no way to stop one, and that is where stale renders came
 * from.** One picture is drawn per person per kind, so while a row said
 * it was working, asking again returned that row rather than drawing.
 * A render whose worker had died held the progress card open and the
 * feature shut for the ten minutes the server's sweep took to reclaim
 * it, and somebody who had merely picked the wrong garment waited the
 * same ten minutes.
 *
 * Two things can silently go wrong here and neither is a type error.
 * The path parameter can be dropped, which sends a request to a literal
 * `{render_id}` and 404s. And the wrong list can be invalidated: the
 * avatar screen reads `current` while the progress card reads
 * `renders`, so refreshing one leaves the other still saying "drawing"
 * - a stop that worked on the server and not on the screen, which is
 * indistinguishable from one that did nothing.
 */

import { renderHook, waitFor } from '@testing-library/react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';

import { api } from '@/api/client';
import { avatarKeys, useCancelRender } from '@/api/queries/avatar';

jest.mock('@/api/client', () => ({
  api: { POST: jest.fn() },
  API_BASE_URL: 'http://example.invalid',
}));

const post = api.POST as unknown as jest.Mock;

const RENDER_ID = '7f1d2c3b-4a59-4c7e-8b21-9f0e5d6c4a33';

let client: QueryClient;
let invalidated: unknown[][];

function wrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  post.mockReset();
  post.mockResolvedValue({ data: { id: RENDER_ID, state: 'failed' } });

  client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  invalidated = [];
  // Recorded, then passed through, so the cache still behaves normally
  // and the test only observes which keys were asked for.
  const real = client.invalidateQueries.bind(client);
  jest
    .spyOn(client, 'invalidateQueries')
    .mockImplementation(((filters?: { queryKey?: readonly unknown[] }) => {
      if (filters?.queryKey) invalidated.push([...filters.queryKey]);
      return real(filters as never);
    }) as typeof client.invalidateQueries);
});

test('it posts to the cancel path with the render as a path parameter', async () => {
  const { result } = await renderHook(() => useCancelRender(), { wrapper });

  result.current.mutate(RENDER_ID);
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  expect(post).toHaveBeenCalledTimes(1);
  const [path, options] = post.mock.calls[0];
  expect(path).toBe('/v1/avatar/renders/{render_id}/cancel');
  expect(options.params.path.render_id).toBe(RENDER_ID);
});

test('it sends no body, because nothing is being changed but the state', async () => {
  const { result } = await renderHook(() => useCancelRender(), { wrapper });

  result.current.mutate(RENDER_ID);
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  expect(post.mock.calls[0][1].body).toBeUndefined();
});

test('it re-reads both the render list and the current avatar', async () => {
  const { result } = await renderHook(() => useCancelRender(), { wrapper });

  result.current.mutate(RENDER_ID);
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  const keys = invalidated.map((key) => JSON.stringify(key));
  expect(keys).toContain(JSON.stringify(avatarKeys.renders));
  expect(keys).toContain(JSON.stringify(avatarKeys.current));
});

test('a failed cancel is reported rather than swallowed', async () => {
  // The screen keeps showing "Stopping" on a rejection, so the caller
  // has to be able to see it. A mutation that resolves on failure would
  // leave the button looking as though it had worked.
  post.mockRejectedValueOnce(new Error('offline'));

  const { result } = await renderHook(() => useCancelRender(), { wrapper });
  result.current.mutate(RENDER_ID);

  await waitFor(() => expect(result.current.isError).toBe(true));
});
