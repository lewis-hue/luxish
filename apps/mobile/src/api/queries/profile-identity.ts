/**
 * The public half of an identity: handle, bio, and links off this app.
 *
 * **Two readers, two shapes.** `useMyProfile` is what the owner sees,
 * including a bio still in review and the note saying why one was
 * held. `usePublicProfile` is what a stranger sees, which is the
 * approved bio and nothing about its state.
 *
 * **Links are a platform and a handle.** The server builds the address
 * and sends it back; the app never constructs one, because the whole
 * point of storing them this way is that a link can only ever point at
 * the platform it claims.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const profileKeys = {
  mine: ['profile', 'me'] as const,
  public: (handle: string) => ['profile', 'public', handle] as const,
};

export type BioState = 'pending_review' | 'published' | 'held';

export interface SocialLink {
  platform: string;
  handle: string;
  url: string;
}

export interface MyProfile {
  userId: string;
  handle: string | null;
  /** What you last typed, whatever state it is in. */
  bio: string | null;
  bioState: BioState;
  /** The banner you chose, whatever state the screen has it in. */
  bannerAssetId: string | null;
  bannerState: BioState;
  /** Why it was held, in words shown to you and nobody else. */
  bannerNote: string | null;
  /** Why it was held, shown to its author and nobody else. */
  bioNote: string | null;
  links: SocialLink[];
  /** Which platforms a link may point at. */
  platforms: string[];
  /**
   * Your fits and your two follow lists are yours alone.
   *
   * Not a consent: `community_sharing` is a grant about the shelf of
   * other people's looks you kept, and one switch answering two
   * different questions is how a privacy control ends up meaning
   * neither.
   */
  private: boolean;
}

export interface PublicProfile {
  userId: string;
  handle: string | null;
  /** The approved bio, or nothing. One in review does not cross. */
  bio: string | null;
  links: SocialLink[];
}

function mapLinks(raw: readonly Record<string, unknown>[] | undefined): SocialLink[] {
  return (raw ?? []).map((link) => ({
    platform: String(link.platform),
    handle: String(link.handle),
    url: String(link.url),
  }));
}

export function useMyProfile(enabled: boolean) {
  return useQuery<MyProfile>({
    queryKey: profileKeys.mine,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/profiles/me');
      return {
        userId: String(data?.user_id ?? ''),
        handle: data?.handle ?? null,
        bio: data?.bio ?? null,
        bioState: (data?.bio_state ?? 'published') as BioState,
        bannerAssetId: data?.banner_asset_id
          ? String(data.banner_asset_id)
          : null,
        bannerState: (data?.banner_state ?? 'published') as BioState,
        bannerNote: data?.banner_note ?? null,
        bioNote: data?.bio_note ?? null,
        links: mapLinks(data?.links as never),
        platforms: (data?.platforms ?? []) as string[],
        private: Boolean(data?.private),
      };
    },
  });
}

export function usePublicProfile(handle: string | null, enabled: boolean) {
  return useQuery<PublicProfile | null>({
    queryKey: profileKeys.public(handle ?? ''),
    enabled: enabled && Boolean(handle),
    queryFn: async () => {
      const { data } = await api.GET('/v1/profiles/{handle}', {
        params: { path: { handle: handle as string } },
      });
      if (!data) return null;
      return {
        userId: String(data.user_id),
        handle: data.handle ?? null,
        bio: data.bio ?? null,
        links: mapLinks(data.links as never),
      };
    },
  });
}

/** The server's own message where it has one: it names the real rule. */
function reason(error: unknown, fallback: string): string {
  const message = (error as { message?: unknown } | undefined)?.message;
  return typeof message === 'string' && message ? message : fallback;
}

export function useUpdateProfile() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      handle?: string;
      bio?: string | null;
      links?: Record<string, string>;
      /**
       * A picture uploaded with kind `profile_banner`, or `null` to
       * take the current one down. Omitting the key leaves it alone -
       * sending it unchanged would put it back into review.
       */
      bannerAssetId?: string | null;
      /** Keep your fits and your two follow lists to yourself. */
      private?: boolean;
    }) => {
      const { bannerAssetId, ...rest } = input;
      const { data, error } = await api.PATCH('/v1/profiles/me', {
        body: {
          ...rest,
          ...('bannerAssetId' in input
            ? { banner_asset_id: bannerAssetId }
            : {}),
        } as never,
      });
      if (error || !data) {
        throw new Error(reason(error, 'That did not save.'));
      }
      return data;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: profileKeys.mine });
    },
  });
}
