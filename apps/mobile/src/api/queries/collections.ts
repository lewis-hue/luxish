/**
 * Wardrobe folders: a name, and the garments filed under it.
 *
 * **A garment sits in several.** Work and Travel overlap by design, so
 * membership is a set operation rather than a move — putting the navy
 * blazer in Travel does not take it out of Work.
 *
 * **Deleting a folder never deletes clothes.** The server guarantees it;
 * the copy on the button says it, because somebody tidying their folders
 * has to be sure before they tap.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const collectionKeys = {
  all: ['wardrobe', 'collections'] as const,
};

export interface WardrobeFolder {
  id: string;
  name: string;
  description: string | null;
  /** Garment ids, server-side, excluding anything since deleted. */
  garmentIds: string[];
}

function map(item: Record<string, unknown>): WardrobeFolder {
  return {
    id: String(item.id),
    name: String(item.name),
    description: (item.description as string | null) ?? null,
    garmentIds: ((item.garment_ids as string[]) ?? []).map(String),
  };
}

export function useFolders(enabled: boolean) {
  return useQuery<WardrobeFolder[]>({
    queryKey: collectionKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/wardrobe/collections');
      return (data?.items ?? []).map((item) => map(item as never));
    },
  });
}

/** The server's own message where it has one: it names the real rule. */
async function reason(error: unknown, fallback: string): Promise<string> {
  const message = (error as { message?: string } | undefined)?.message;
  return message && typeof message === 'string' ? message : fallback;
}

export function useCreateFolder() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const { data, error } = await api.POST('/v1/wardrobe/collections', {
        body: { name } as never,
      });
      if (error || !data) {
        throw new Error(await reason(error, 'That folder name did not work.'));
      }
      return map(data as never);
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: collectionKeys.all });
    },
  });
}

export function useRenameFolder() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }) => {
      const { data, error } = await api.PATCH('/v1/wardrobe/collections/{collection_id}', {
        params: { path: { collection_id: id } },
        body: { name } as never,
      });
      if (error || !data) {
        throw new Error(await reason(error, 'That name did not work.'));
      }
      return map(data as never);
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: collectionKeys.all });
    },
  });
}

export function useDeleteFolder() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE('/v1/wardrobe/collections/{collection_id}', {
        params: { path: { collection_id: id } },
      });
      if (error) throw new Error('Could not delete that folder.');
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: collectionKeys.all });
    },
  });
}

/** Put garments in a folder, or take them out. Idempotent either way. */
export function useSetFolderMembers() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      garmentIds,
      present,
    }: {
      id: string;
      garmentIds: string[];
      present: boolean;
    }) => {
      const path = '/v1/wardrobe/collections/{collection_id}/garments' as const;
      const options = {
        params: { path: { collection_id: id } },
        body: { garment_ids: garmentIds },
      };
      const { data, error } = present
        ? await api.PUT(path, options as never)
        : await api.DELETE(path, options as never);
      if (error || !data) throw new Error('Could not file those.');
      return map(data as never);
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: collectionKeys.all });
    },
  });
}
