/**
 * API reachability.
 *
 * `/healthz` is the only route that needs no token, which makes it the one honest
 * way for the app to tell a developer "the backend is or is not there" — distinct
 * from "you are not signed in". Those two look identical in a feed that fails to
 * load, and distinguishing them is most of local debugging.
 */

import { useQuery } from '@tanstack/react-query';

import { api, API_BASE_URL, describeError } from '@/api/client';

export const healthKeys = { status: ['health'] as const };

export interface ApiHealth {
  reachable: boolean;
  environment: string | null;
  baseUrl: string;
  problem: string | null;
}

export function useApiHealth() {
  return useQuery<ApiHealth>({
    queryKey: healthKeys.status,
    queryFn: async () => {
      try {
        const { data } = await api.GET('/healthz');
        return {
          reachable: true,
          environment: data?.environment ?? null,
          baseUrl: API_BASE_URL,
          problem: null,
        };
      } catch (error) {
        // A failed reachability check is an answer, not an error — returning it
        // keeps the row rendering instead of throwing to an error boundary.
        return {
          reachable: false,
          environment: null,
          baseUrl: API_BASE_URL,
          problem: describeError(error).body,
        };
      }
    },
    // Cheap and useful while developing; still not a poll loop.
    staleTime: 15_000,
    retry: false,
  });
}
