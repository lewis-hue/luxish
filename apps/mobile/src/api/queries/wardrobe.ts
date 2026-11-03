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

/**
 * Remove many garments at once.
 *
 * Goes through the server's bulk path rather than looping single deletes:
 * each one writes a media tombstone, and a loop of them from the device
 * would be N round trips that can half-fail with no record of where it
 * stopped. The server answers per item, so a stale id in the selection is
 * reported rather than failing the batch.
 */
export function useBulkDeleteGarments() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (garmentIds: string[]) => {
      const { data, error } = await api.POST('/v1/wardrobe/garments/bulk/delete', {
        body: { garment_ids: garmentIds } as never,
      });
      if (error || !data) throw new Error('Could not remove those.');
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ['wardrobe'] });
      void queries.invalidateQueries({ queryKey: ['wardrobe', 'collections'] });
    },
  });
}
