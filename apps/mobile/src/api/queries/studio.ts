/**
 * The studio's one read.
 *
 * One windowed overview rather than a query per card, so every number on
 * the screen answers over the same days and two cards can never disagree
 * about what "this week" means.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';

export type StudioWindow = '7d' | '28d' | 'all';

export interface TopFit {
  postId: string;
  /** Distinct people who saved or reacted to it. Not events. */
  people: number;
  saves: number;
}

export interface StudioOverview {
  window: StudioWindow;
  /** Fits this person has published, which is what the rest is about. */
  fits: number;
  saves: number;
  reach: number;
  followers: number;
  followersGained: number;
  /** One count per day, oldest first. Drawn as bars, never re-derived. */
  series: number[];
  topFits: TopFit[];
}

export function useStudio(window: StudioWindow, enabled: boolean) {
  return useQuery<StudioOverview>({
    queryKey: ['studio', window] as const,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/studio/overview', {
        params: { query: { window } },
      });
      return {
        window: (data?.window ?? window) as StudioWindow,
        fits: data?.fits ?? 0,
        saves: data?.saves ?? 0,
        reach: data?.reach ?? 0,
        followers: data?.followers ?? 0,
        followersGained: data?.followers_gained ?? 0,
        series: data?.series ?? [],
        topFits: (data?.top_fits ?? []).map((item) => ({
          postId: String(item.post_id),
          people: item.people,
          saves: item.saves,
        })),
      };
    },
  });
}

/** The chart caption: the best day, as a sentence instead of an axis. */
export function bestDayLine(series: readonly number[], now: Date = new Date()): string | null {
  if (series.length === 0) return null;
  const peak = Math.max(...series);
  if (peak <= 0) return null;
  const index = series.lastIndexOf(peak);
  const daysAgo = series.length - 1 - index;
  const day = new Date(now);
  day.setDate(day.getDate() - daysAgo);
  const label = day.toLocaleDateString(undefined, { day: 'numeric', month: 'long' });
  return `Best day ${label}, ${peak} ${peak === 1 ? 'touch' : 'touches'}.`;
}
