/**
 * Regional style context.
 *
 * `place` is a name the user typed, never a device coordinate — the backend has no
 * field for a device fix by design. Omitting it is a supported call, which is what
 * makes styling work for someone who declined location (acceptance criterion 5).
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';

export const regionalKeys = {
  context: (place: string | null, occasion: string | null) =>
    ['regional', 'context', place, occasion] as const,
};

export function useRegionalContext(
  place: string | null,
  occasion: string | null = null,
) {
  return useQuery({
    queryKey: regionalKeys.context(place, occasion),
    queryFn: async () => {
      const { data } = await api.GET('/v1/regional/context', {
        params: {
          query: {
            ...(place ? { place } : {}),
            ...(occasion ? { occasion } : {}),
          },
        },
      });
      return data;
    },
    // Reviewed editorial knowledge; it does not change within a session.
    staleTime: 10 * 60_000,
  });
}
