/**
 * The inbox.
 *
 * Derived on the server from what already happened rather than written
 * alongside it, so there is nothing to push here and nothing to mark
 * individually — the read state is one watermark per person. See
 * `app/domain/notifications.py` for why that trade was made.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const notificationKeys = { inbox: ['notifications'] as const };

export type NotificationKind =
  | 'wardrobe_sorted'
  | 'stylist_ready'
  | 'fit_reactions';

export interface Notification {
  kind: NotificationKind;
  occurredAt: string;
  title: string;
  body: string;
  /** An app route, or null when the inbox itself is the destination. */
  target: string | null;
  /** Distinct people behind a cross-user item. Null for everything else. */
  people: number | null;
}

export interface Inbox {
  items: readonly Notification[];
  unread: number;
  windowDays: number;
}

export function useInbox(enabled: boolean) {
  return useQuery<Inbox>({
    queryKey: notificationKeys.inbox,
    enabled,
    // Shorter than the app default: the whole value of a badge is that it is
    // roughly current, and an hour-stale unread count is worse than none.
    staleTime: 60_000,
    queryFn: async () => {
      const { data } = await api.GET('/v1/notifications');
      return {
        items: (data?.items ?? []).map((item) => ({
          kind: item.kind as NotificationKind,
          occurredAt: item.occurred_at,
          title: item.title,
          body: item.body,
          target: item.target ?? null,
          people: item.people ?? null,
        })),
        unread: data?.unread ?? 0,
        windowDays: data?.window_days ?? 14,
      };
    },
  });
}

/**
 * Move the read watermark to now.
 *
 * Called when the inbox is opened rather than per item: there is one
 * watermark, so marking anything read marks everything before it read. The
 * list itself is unchanged — an inbox that empties when you look at it has
 * thrown away the thing you opened it to find.
 */
export function useMarkInboxRead() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.POST('/v1/notifications/read');
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: notificationKeys.inbox });
    },
  });
}

/**
 * How long ago, in the shortest true form.
 *
 * Minutes under an hour, hours under a day, then days. Nothing here says
 * "just now" for something three seconds old and then "1 minute ago" a
 * moment later; the coarsest unit that is still accurate reads as calm
 * rather than as a stopwatch.
 */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const minutes = Math.max(0, Math.round((now.getTime() - then) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
