/**
 * What the user has agreed to, and the one place that changes it.
 *
 * `ai_processing` is the gate on every model call made on someone's behalf.
 * The server refuses to route a styling run without it, correctly — but until
 * the app could grant it, that refusal surfaced as "the styling service is
 * unavailable", which was both wrong and unfixable from inside the product.
 *
 * Asked for at the point of use rather than at sign-up. A consent collected
 * in a wall of toggles before anyone has seen what the app does is a consent
 * nobody read; asked when someone taps "Style me", it is a question about
 * something they are visibly trying to do.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const consentKeys = { all: ['consents'] as const };

/** The kinds the service records. Mirrors the server's closed set. */
export type ConsentKind =
  | 'publication'
  | 'ai_processing'
  | 'location_precise'
  | 'location_coarse'
  | 'analytics'
  | 'community_sharing';

export interface Consent {
  kind: ConsentKind;
  granted: boolean;
  /** Null when never asked, which is a different fact from withdrawn. */
  grantedAt: string | null;
  revokedAt: string | null;
}

export function useConsents(enabled: boolean) {
  return useQuery<readonly Consent[]>({
    queryKey: consentKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/consents');
      return (data?.items ?? []).map((item) => ({
        kind: item.kind as ConsentKind,
        granted: item.granted,
        grantedAt: item.granted_at ?? null,
        revokedAt: item.revoked_at ?? null,
      }));
    },
  });
}

/**
 * Grant or withdraw one consent.
 *
 * One mutation for both directions, mirroring the endpoint. Making withdrawal
 * a different path is how an app ends up with a one-tap grant and a
 * three-screen withdrawal, which is not freely given consent.
 */
export function useSetConsent() {
  const queries = useQueryClient();

  return useMutation({
    mutationFn: async (input: { kind: ConsentKind; granted: boolean; source?: string }) => {
      const { data } = await api.PUT('/v1/consents/{kind}', {
        params: { path: { kind: input.kind } },
        body: { granted: input.granted, source: input.source ?? 'app' },
      });
      return Boolean(data?.granted);
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: consentKeys.all });
    },
  });
}

/** True when this user has agreed to have their wardrobe sent to a model. */
export function hasAiConsent(consents: readonly Consent[] | undefined): boolean {
  return Boolean(consents?.find((c) => c.kind === 'ai_processing')?.granted);
}

/**
 * True when this user has agreed to appear in other people's feeds.
 *
 * Off by default, and that default is load-bearing. Following needs no
 * approval in this app, so without the grant somebody could learn your saved
 * collection by tapping Follow — the Saved screen is a personal shelf and
 * nothing ever said otherwise.
 */
export function hasCommunityConsent(
  consents: readonly Consent[] | undefined,
): boolean {
  return Boolean(consents?.find((c) => c.kind === 'community_sharing')?.granted);
}
