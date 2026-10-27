/**
 * Wardrobe queries.
 *
 * Cursor pagination throughout, because the API exposes no offsets — an offset over
 * a list the user is actively adding to silently skips and repeats items.
 */

import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const wardrobeKeys = {
  all: ['wardrobe'] as const,
  garments: (filters: GarmentFilters) => ['wardrobe', 'garments', filters] as const,
  garment: (id: string) => ['wardrobe', 'garment', id] as const,
};

export interface GarmentFilters {
  category?: string;
  availability?: string;
}

export function useGarments(filters: GarmentFilters = {}) {
  return useInfiniteQuery({
    queryKey: wardrobeKeys.garments(filters),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const { data } = await api.GET('/v1/wardrobe/garments', {
        params: { query: { cursor: pageParam, ...filters } },
      });
      return data;
    },
    getNextPageParam: (lastPage) => lastPage?.next_cursor ?? undefined,
  });
}

/**
 * Applies a user correction.
 *
 * Corrections outrank model inference permanently (the backend resolves
 * `effective_attributes` per key), so this invalidates rather than patching the
 * cache by hand — the server's resolution is the truth, not ours.
 */
export function useCorrectGarment(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (confirmed: Record<string, unknown>) => {
      const { data } = await api.PATCH('/v1/wardrobe/garments/{garment_id}', {
        params: { path: { garment_id: id } },
        body: { confirmed_attributes: confirmed },
      });
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: wardrobeKeys.all });
    },
  });
}
