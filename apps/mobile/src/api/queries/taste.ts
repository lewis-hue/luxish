/**
 * What somebody says they like, asked once at sign-up.
 *
 * **The vocabularies come from the server**, not from a constant next to the
 * screen. An aesthetic the app offers but the server does not know is an
 * answer rejected after somebody taps it; one the server knows but the app
 * does not offer is a question nobody can answer. Two lists in two places
 * drift the first time either changes.
 *
 * Nothing here is a gate. Browsing works without an account and without
 * answering, so a failed fetch or a declined question leaves the app exactly
 * as usable as it was.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const tasteKeys = {
  mine: ['taste'] as const,
  options: ['taste', 'options'] as const,
};

export type Lens = 'occasion' | 'aesthetic' | 'formula';

export interface Taste {
  aesthetics: readonly string[];
  occasions: readonly string[];
  dressCode: string;
  goal: string | null;
  /** Whether anything was said. False for "declined" *and* "not yet asked". */
  answered: boolean;
  /** Which order to show the Discover shelves in. Decided by the goal. */
  lensOrder: readonly Lens[];
}

export interface TasteOptions {
  aesthetics: readonly string[];
  occasions: readonly string[];
  dressCodes: readonly string[];
  goals: readonly string[];
  maxChoices: number;
  /**
   * How many occasions may be sent.
   *
   * Separate from `maxChoices` because the two questions are not
   * the same kind of question. "Where you actually need outfits" is
   * factual, and a save of eleven honest answers was rejected by a
   * server that capped it at six while the screen said "Pick any".
   */
  maxOccasions: number;
}

export const DEFAULT_LENS_ORDER: readonly Lens[] = ['occasion', 'aesthetic', 'formula'];

export function useTaste(enabled: boolean) {
  return useQuery<Taste>({
    queryKey: tasteKeys.mine,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/taste');
      return {
        aesthetics: data?.aesthetics ?? [],
        occasions: data?.occasions ?? [],
        dressCode: data?.dress_code ?? 'unspecified',
        goal: data?.goal ?? null,
        answered: data?.answered ?? false,
        lensOrder: (data?.lens_order ?? DEFAULT_LENS_ORDER) as Lens[],
      };
    },
  });
}

export function useTasteOptions() {
  return useQuery<TasteOptions>({
    queryKey: tasteKeys.options,
    // A vocabulary, not anybody's data: it needs no session and changes only
    // when the app ships.
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    queryFn: async () => {
      const { data } = await api.GET('/v1/taste/options');
      return {
        aesthetics: data?.aesthetics ?? [],
        occasions: data?.occasions ?? [],
        dressCodes: data?.dress_codes ?? [],
        goals: data?.goals ?? [],
        maxChoices: data?.max_choices ?? 6,
        maxOccasions: data?.max_occasions ?? 22,
      };
    },
  });
}

export function useSetTaste() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (next: {
      aesthetics: readonly string[];
      occasions: readonly string[];
      dressCode: string;
      goal: string | null;
    }) => {
      const { data } = await api.PUT('/v1/taste', {
        body: {
          aesthetics: [...next.aesthetics],
          occasions: [...next.occasions],
          dress_code: next.dressCode,
          goal: next.goal,
        },
      });
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: tasteKeys.mine });
    },
  });
}

export interface TasteProfile {
  /** Collection ids for "how to wear what you own", best fit first. */
  formula: readonly string[];
  /** Collection ids for "the look", most reached-for first. */
  aesthetics: readonly string[];
  /** How many garments this rests on. */
  wardrobeSize: number;
  /** Slots with too little in them to build an outfit from. */
  gaps: readonly string[];
  answered: boolean;
}

/**
 * Which collections to lead each shelf with, for this person.
 *
 * Three queries on the server and no model call, which is what makes it safe
 * to ask for on every Discover open. The conclusion crosses the wire, not the
 * signals: a client has no use for somebody's garment counts and every reason
 * not to hold them.
 */
export function useTasteProfile(enabled: boolean) {
  return useQuery<TasteProfile>({
    queryKey: ['taste', 'profile'],
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/profile/taste');
      return {
        formula: data?.formula ?? [],
        aesthetics: data?.aesthetics ?? [],
        wardrobeSize: data?.wardrobe_size ?? 0,
        gaps: data?.gaps ?? [],
        answered: data?.answered ?? false,
      };
    },
  });
}

/**
 * Put a shelf's collections in the order a profile implies.
 *
 * Same shape as `orderShelves` and the same -1 hazard: a collection the
 * profile does not rank must keep its place rather than jumping to the front.
 * Everything is kept — a shelf that drops the collections the profile did not
 * mention is a shelf that gets shorter the more we know about somebody, which
 * is exactly backwards.
 */
export function orderCollections<T extends { id: string }>(
  collections: readonly T[],
  order: readonly string[] | undefined,
): readonly T[] {
  if (!order?.length) return collections;
  const rank = (item: T, fallback: number): number => {
    const found = order.indexOf(item.id);
    return found === -1 ? order.length + fallback : found;
  };
  return collections
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item, a.index) - rank(b.item, b.index))
    .map((entry) => entry.item);
}

/**
 * Put shelves in the order a stated taste implies.
 *
 * Takes the shelves rather than mutating them, and keeps every one: leading a
 * lens must never drop the others, or answering one question would remove two
 * thirds of Discover.
 *
 * A shelf whose lens the order does not mention keeps its original position
 * rather than jumping to the front, which is what a bare `indexOf` would do
 * with its -1. That is the quiet failure here — add a lens on one side only
 * and the layout silently reshuffles instead of ignoring it.
 */
export function orderShelves<T extends { id: Lens }>(
  shelves: readonly T[],
  order: readonly Lens[] | undefined,
): readonly T[] {
  if (!order?.length) return shelves;
  const rank = (shelf: T, fallback: number): number => {
    const found = order.indexOf(shelf.id);
    return found === -1 ? order.length + fallback : found;
  };
  return shelves
    .map((shelf, index) => ({ shelf, index }))
    .sort((a, b) => rank(a.shelf, a.index) - rank(b.shelf, b.index))
    .map((entry) => entry.shelf);
}

/** Plain-language labels for the answers the server speaks in ids. */
export const DRESS_CODE_LABELS: Readonly<Record<string, string>> = {
  none: 'No dress code',
  smart_casual: 'Smart casual',
  business: 'Business',
  formal: 'Formal',
  unspecified: 'Rather not say',
};

export const GOAL_LABELS: Readonly<Record<string, string>> = {
  more_from_what_i_own: 'Get more out of what I own',
  what_to_wear_to: 'Work out what to wear to things',
  find_my_look: 'Find my look',
};
