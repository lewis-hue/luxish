/**
 * The plan, its state, and the monthly allowance.
 *
 * Everything here is honest about what stands behind it: the server's
 * `simulated` flag is carried through untouched and rendered by every
 * screen that shows a subscription, because a development fixture must
 * never read as a live billing relationship.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const billingKeys = { entitlements: ['billing', 'entitlements'] as const };

export interface Entitlements {
  plan: 'free' | 'plus';
  /** `ending` is active with renewal off: "ends on" is a different
   *  sentence from "renews on". */
  state: 'free' | 'active' | 'ending';
  store: 'simulated' | 'app_store' | 'play_billing' | null;
  periodEnd: string | null;
  autoRenew: boolean;
  allowance: number;
  used: number;
  remaining: number;
  resetsAt: string;
  simulated: boolean;
}

export function useEntitlements(enabled: boolean) {
  return useQuery<Entitlements>({
    queryKey: billingKeys.entitlements,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/billing/entitlements');
      return {
        plan: (data?.plan ?? 'free') as Entitlements['plan'],
        state: (data?.state ?? 'free') as Entitlements['state'],
        store: (data?.store ?? null) as Entitlements['store'],
        periodEnd: data?.period_end ?? null,
        autoRenew: data?.auto_renew ?? false,
        allowance: data?.allowance ?? 0,
        used: data?.used ?? 0,
        remaining: data?.remaining ?? 0,
        resetsAt: data?.resets_at ?? new Date().toISOString(),
        simulated: data?.simulated ?? false,
      };
    },
  });
}

/** Start the simulated subscription. Development builds only; the server
 *  refuses anywhere else, and the screen says so beside the button. */
export function useSimulatedSubscribe() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/v1/billing/simulated/subscribe', {
        body: { plan: 'plus' },
      });
      if (error) throw new Error('The simulated store refused.');
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: billingKeys.entitlements });
    },
  });
}

/** Cancel or resume. Access always runs to the end of the period. */
export function useSetAutoRenew() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (autoRenew: boolean) => {
      const { data, error } = await api.POST('/v1/billing/auto-renew', {
        body: { auto_renew: autoRenew },
      });
      if (error) throw new Error('Could not change the renewal.');
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: billingKeys.entitlements });
    },
  });
}

/** "4 June", for period and reset dates. Local, since both are about the
 *  reader's own calendar. */
export function shortDate(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'long' });
}

/**
 * The meter, as one calm sentence.
 *
 * "9 of 12 stylist runs left this month. Resets 1 December." Always
 * visible rather than appearing near the limit: a person who can see how
 * close they are decides when to change plans, instead of being ambushed
 * by a block.
 */
export function meterLine(ent: Pick<Entitlements, 'remaining' | 'allowance' | 'resetsAt'>): string {
  const runs = ent.allowance === 1 ? 'stylist run' : 'stylist runs';
  return `${ent.remaining} of ${ent.allowance} ${runs} left this month. Resets ${shortDate(ent.resetsAt)}.`;
}
