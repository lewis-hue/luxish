/**
 * Which kinds of updates this account wants to hear about.
 *
 * Stored on the server beside the read watermark, so a choice made on one
 * phone holds on the next one. The server enforces the three inbox kinds
 * where the inbox is built; `planReminders` is this device's to honour,
 * because the reminders are local notifications the server never sends.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { notificationKeys } from '@/api/queries/notifications';

export const prefsKeys = { all: ['notification-prefs'] as const };

export interface NotificationPrefs {
  wardrobeSorted: boolean;
  stylistReady: boolean;
  fitReactions: boolean;
  planReminders: boolean;
}

export function useNotificationPrefs(enabled: boolean) {
  return useQuery<NotificationPrefs>({
    queryKey: prefsKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/notifications/preferences');
      return {
        wardrobeSorted: data?.wardrobe_sorted ?? true,
        stylistReady: data?.stylist_ready ?? true,
        fitReactions: data?.fit_reactions ?? true,
        planReminders: data?.plan_reminders ?? true,
      };
    },
  });
}

/**
 * Flip one switch.
 *
 * Optimistic, because a toggle that answers a second late reads as broken:
 * the cache is updated before the request and rolled back if it fails. The
 * inbox query is invalidated on success because muting a kind changes what
 * the server builds.
 */
export function useSetNotificationPref() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (change: Partial<NotificationPrefs>) => {
      const body: Record<string, boolean> = {};
      if (change.wardrobeSorted !== undefined) body.wardrobe_sorted = change.wardrobeSorted;
      if (change.stylistReady !== undefined) body.stylist_ready = change.stylistReady;
      if (change.fitReactions !== undefined) body.fit_reactions = change.fitReactions;
      if (change.planReminders !== undefined) body.plan_reminders = change.planReminders;
      const { data, error } = await api.PATCH('/v1/notifications/preferences', {
        body: body as never,
      });
      if (error) throw new Error('Could not save that setting.');
      return data;
    },
    onMutate: async (change) => {
      await queries.cancelQueries({ queryKey: prefsKeys.all });
      const before = queries.getQueryData<NotificationPrefs>(prefsKeys.all);
      if (before) {
        queries.setQueryData<NotificationPrefs>(prefsKeys.all, { ...before, ...change });
      }
      return { before };
    },
    onError: (_error, _change, context) => {
      if (context?.before) queries.setQueryData(prefsKeys.all, context.before);
    },
    onSettled: () => {
      void queries.invalidateQueries({ queryKey: prefsKeys.all });
      void queries.invalidateQueries({ queryKey: notificationKeys.inbox });
    },
  });
}
