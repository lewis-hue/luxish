/**
 * Who the signed-in person is.
 *
 * The auth state knows only that a session exists and when it expires, which
 * is all it needs to gate a request. It is not enough to greet somebody by
 * name, and a Profile screen that can only say "Signed in" is a screen that
 * knows less about you than your own device does.
 *
 * Only fetched when there is a session. Asking while signed out would be a
 * guaranteed 401, which the client would then treat as a revoked token and
 * clear a session that was never there.
 */

import { Directory, File, Paths } from 'expo-file-system';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

export const meKeys = { current: ['me'] as const };

export interface Me {
  userId: string;
  email: string | null;
  emailVerified: boolean;
  displayName: string | null;
  /** A photograph they uploaded, as a media asset id. Null for most people. */
  profilePhotoAssetId: string | null;
}

/**
 * The best name to greet someone by, or null if we have none.
 *
 * Falls back from display name to the local part of the email, because
 * "lewie" is a greeting and "lewie@example.com" is a database field. Never
 * falls back to the user id: a UUID is worse than no name at all.
 */
/**
 * What to call somebody on screen.
 *
 * **A first name, not a full one.** "Hey, Lewis" is a greeting; "Hey, Lewis
 * Muguna" is a salutation on a letter from a bank. The display name is
 * whatever the identity provider holds — often first and last — so the first
 * word of it is taken and the rest left alone.
 *
 * Falls back to the email's local part, which is frequently a name and
 * occasionally not. It is split on separators and capitalised, so
 * `lewis.muguna@` greets as "Lewis" rather than "lewis.muguna". A local part
 * that is plainly not a name — digits, a single letter — yields nothing, and
 * the caller shows its unnamed wording instead of greeting a string.
 */
export function greetingName(me: Me | undefined): string | null {
  if (!me) return null;

  const display = me.displayName?.trim();
  if (display) {
    const first = display.split(/\s+/)[0];
    if (first) return first;
  }

  const local = me.email?.split('@')[0]?.trim();
  if (!local) return null;
  // `lewis.muguna`, `lewis_muguna`, `lewis-muguna` and `lewis+tag` all carry
  // the name in the first segment.
  const head = local.split(/[._+-]/)[0] ?? '';
  // Two letters is the shortest real name; anything with a digit in it is an
  // account handle rather than a person, and greeting somebody "Hey, user42"
  // is worse than not greeting them.
  if (head.length < 2 || /\d/.test(head)) return null;
  return head.charAt(0).toUpperCase() + head.slice(1);
}

export function useMe(enabled: boolean) {
  return useQuery<Me | null>({
    queryKey: meKeys.current,
    enabled,
    // Identity changes when someone signs in or out, and both of those
    // already remount this. Re-fetching on every focus would spend a request
    // to learn what has not changed.
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      const { data } = await api.GET('/v1/auth/me');
      if (!data) return null;
      return {
        userId: String(data.user_id),
        email: data.email ?? null,
        emailVerified: Boolean(data.email_verified),
        displayName: data.display_name ?? null,
        profilePhotoAssetId: data.profile_photo_asset_id
          ? String(data.profile_photo_asset_id)
          : null,
      };
    },
  });
}

/**
 * Change the name and photograph somebody shows in the app.
 *
 * **Only sends what changed.** The endpoint reads the fields present in the
 * body and leaves the rest alone, which is what lets somebody edit their
 * name without the request quietly removing their photograph. Passing
 * `null` is how a field is cleared, so `undefined` and `null` mean different
 * things here and the two must not be collapsed.
 */
export function useUpdateMe() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (changes: {
      displayName?: string | null;
      profilePhotoAssetId?: string | null;
    }) => {
      const body: Record<string, unknown> = {};
      if ('displayName' in changes) body.display_name = changes.displayName;
      if ('profilePhotoAssetId' in changes) {
        body.profile_photo_asset_id = changes.profilePhotoAssetId;
      }
      const { data } = await api.PATCH('/v1/auth/me', { body: body as never });
      return data;
    },
    onSuccess: () => {
      // The greeting on Discover reads the same query, so one invalidation
      // updates both screens.
      void queries.invalidateQueries({ queryKey: meKeys.current });
    },
  });
}

/**
 * The profile photograph, fetched to a file on this device.
 *
 * Not rendered straight from a URL, for the same reason garment cut-outs and
 * the avatar are not: the delivery endpoint needs a bearer token, and a
 * token in an `Image` header is a token that expires behind a cached
 * picture — the image then 401s forever and the only fix is reinstalling.
 *
 * Kept in `document` rather than `cache`: it is small, it changes only when
 * somebody changes it, and it is on the first screen of Profile, so losing
 * it to a cache eviction means a visible blank on a screen that was fine a
 * moment ago.
 */
export function useProfilePhoto(assetId: string | null): string | null {
  const { data } = useQuery<string | null>({
    queryKey: ['me', 'photo', assetId],
    enabled: Boolean(assetId),
    // The file is keyed by asset id, so the only thing that changes it is a
    // new id — which is a new query key anyway.
    staleTime: Infinity,
    // Immutable, so the `refetchOnMount: 'always'` default would
    // spend a request per mount to be told the same thing.
    refetchOnMount: false,
    queryFn: async () => {
      if (!assetId) return null;
      const token = await accessToken();
      if (!token) return null;

      const dir = new Directory(Paths.document, 'profile');
      if (!dir.exists) dir.create({ intermediates: true });
      const target = new File(dir, assetId);
      if (target.exists) return target.uri;

      try {
        const got = await File.downloadFileAsync(
          `${API_BASE_URL}/v1/uploads/local/${assetId}`,
          target,
          { headers: { Authorization: `Bearer ${token}` }, idempotent: true },
        );
        return got.uri;
      } catch (caught) {
        // A picture that failed to download is a missing picture, not a
        // reason to fail the screen it was going to sit on. The portrait
        // falls back to the drawn avatar and then to a monogram.
        if (__DEV__) console.warn('[profile] could not fetch photo', caught);
        return null;
      }
    },
  });
  return data ?? null;
}


/**
 * Close the account for good.
 *
 * **There is a real endpoint and the app was not calling it.** The
 * settings row opened a `/delete-account` page on the web origin -
 * a page that does not exist - while `DELETE /v1/account` sat
 * unused. Somebody who wanted to leave was sent to a dead link.
 *
 * The server soft-deletes, releases the email address for a future
 * signup, and revokes every session including this one. So the
 * token in hand is dead the moment this returns, and the caller has
 * to sign out locally rather than carry on with it.
 */
export function useDeleteAccount() {
  return useMutation({
    mutationFn: async () => {
      const { error } = await api.DELETE('/v1/account');
      if (error) {
        throw new Error('Your account could not be closed. Try again.');
      }
    },
  });
}
