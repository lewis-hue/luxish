/**
 * The planner: what you are wearing, by date.
 *
 * Dates cross the wire as `YYYY-MM-DD` strings and are never turned into
 * `Date` objects for transport. A plan is a *day* in the wearer's calendar,
 * and a `Date` is an instant: round-tripping one through a timezone is how a
 * Thursday plan becomes a Wednesday one for somebody who flew west.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const plannerKeys = {
  all: ['planner'] as const,
  range: (start: string, end: string) => ['planner', start, end] as const,
};

export interface Plan {
  /** `YYYY-MM-DD`. A day, not an instant. */
  plannedFor: string;
  /**
   * The clothes, in the order they were put together.
   *
   * Garments out of this person's own wardrobe. A plan used to name a
   * curated look - a catalogue entry nobody owned - so planning a
   * week produced a wardrobe of clothes the wearer did not have.
   */
  garmentIds: string[];
  /**
   * The fit this day was planned from, when it started on one.
   *
   * Null on most days: planning straight out of the wardrobe
   * references nothing. `referenceAssetId` is that fit's cover, sent
   * with it so a month of days is one request rather than thirty.
   */
  referencePostId: string | null;
  referenceAssetId: string | null;
  note: string | null;
  /** Null is "not answered yet", which is not "no". */
  worn: boolean | null;
}

/** `YYYY-MM-DD` for a local date, without a timezone ever being involved. */
export function isoDay(value: Date): string {
  const year = value.getFullYear();
  const month = `${value.getMonth() + 1}`.padStart(2, '0');
  const day = `${value.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** The Monday of the week a date falls in. Weeks start Monday here. */
export function startOfWeek(value: Date): Date {
  const copy = new Date(value);
  // `getDay()` is 0 for Sunday, so Sunday belongs to the week that began six
  // days earlier rather than the one starting tomorrow.
  const offset = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - offset);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

export function addDays(value: Date, days: number): Date {
  const copy = new Date(value);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export function usePlanner(start: string, end: string, enabled: boolean) {
  return useQuery<Plan[]>({
    queryKey: plannerKeys.range(start, end),
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/planner', {
        params: { query: { start, end } },
      });
      return (data?.items ?? []).map((item) => ({
        plannedFor: item.planned_for,
        garmentIds: (item.garment_ids ?? []).map(String),
        note: item.note ?? null,
        worn: item.worn ?? null,
        referencePostId: item.reference_post_id
          ? String(item.reference_post_id)
          : null,
        referenceAssetId: item.reference_asset_id
          ? String(item.reference_asset_id)
          : null,
      }));
    },
  });
}

export function usePlanDay() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({
      day,
      garmentIds,
      note,
      referencePostId,
    }: {
      day: string;
      /** Replaces whatever was planned: the request states the day. */
      garmentIds: string[];
      note?: string;
      /**
       * The fit this day is being planned from, if it started on one.
       *
       * Omitted rather than sent as null when unchanged, the same
       * rule `note` follows: re-saving a day's clothes must not
       * quietly drop the picture it was planned from.
       */
      referencePostId?: string;
    }) => {
      await api.PUT('/v1/planner/{day}', {
        params: { path: { day } },
        // Each field is omitted rather than sent as null when
        // unchanged, because omitting means "not talking about it"
        // and an empty string clears.
        body: {
          garment_ids: garmentIds,
          ...(note === undefined ? {} : { note }),
          ...(referencePostId === undefined
            ? {}
            : { reference_post_id: referencePostId }),
        },
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: plannerKeys.all });
    },
  });
}

export function useUnplanDay() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (day: string) => {
      await api.DELETE('/v1/planner/{day}', { params: { path: { day } } });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: plannerKeys.all });
    },
  });
}

export function useMarkWorn() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ day, worn }: { day: string; worn: boolean }) => {
      await api.POST('/v1/planner/{day}/worn', {
        params: { path: { day } },
        body: { worn },
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: plannerKeys.all });
    },
  });
}
