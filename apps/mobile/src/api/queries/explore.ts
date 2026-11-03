/**
 * The search screen's categories, each wearing a real fit.
 *
 * Generated cover art describing user content is a catalogue
 * pretending to be a community. These tiles carry a photograph
 * somebody actually posted, picked by the same score the board ranks
 * by, so the picture on a tile is the one that would have led that
 * tag's page anyway.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';

export const exploreKeys = { all: ['feed', 'explore'] as const };

export interface Door {
  /** `tag` today; `group` is reserved for a different destination. */
  kind: string;
  key: string;
  label: string;
  /** How many fits are behind it, for this reader. */
  posts: number;
  /** A real photograph, or null when the best fit has none. */
  coverAssetId: string | null;
}

export interface Explore {
  /** From stated taste. */
  forYou: Door[];
  /** What is busy, for this reader. */
  popular: Door[];
}

function toDoor(item: Record<string, unknown>): Door {
  return {
    kind: String(item.kind ?? 'tag'),
    key: String(item.key),
    label: String(item.label),
    posts: Number(item.posts ?? 0),
    coverAssetId: item.cover_asset_id ? String(item.cover_asset_id) : null,
  };
}

export function useExplore(enabled: boolean) {
  return useQuery<Explore>({
    queryKey: exploreKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/explore');
      return {
        forYou: (data?.for_you ?? []).map((item) => toDoor(item as never)),
        popular: (data?.popular ?? []).map((item) => toDoor(item as never)),
      };
    },
  });
}

export const ideasKeys = { all: ['feed', 'ideas'] as const };

/**
 * Tags this reader keeps reaching for.
 *
 * The same tile as `explore`'s, ranked by what they saved and reacted
 * to rather than by what they said they liked. The two are allowed to
 * disagree: a shelf part-way down the board is a suggestion, and the
 * fits somebody keeps are the best evidence of what they would keep
 * next.
 *
 * Held for the session rather than refetched as the board scrolls -
 * a shelf that reorders itself under the thumb is worse than a stale
 * one, and it is rebuilt on the next cold open anyway.
 */
export function useIdeas(enabled: boolean) {
  return useQuery<Door[]>({
    queryKey: ideasKeys.all,
    enabled,
    staleTime: 10 * 60 * 1000,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/ideas');
      return (data?.items ?? []).map((item) => toDoor(item as never));
    },
  });
}
