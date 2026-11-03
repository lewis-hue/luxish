import * as Location from 'expo-location';
import { useMutation } from '@tanstack/react-query';

import { api } from '@/api/client';

/**
 * Shops somebody could walk into, near where they are.
 *
 * **Asked for, never kept.** The coordinates go straight into one
 * request and are not written anywhere - not to the cache, not to a
 * profile, not to a column. The server rounds them to about a
 * kilometre before they reach the shop directory, which is what the
 * `location_coarse` consent describes.
 *
 * **A mutation rather than a query**, because a position is only
 * worth asking the operating system for when somebody has actually
 * asked to see shops. A `useQuery` here would prompt for location on
 * mount of whatever screen imported it.
 */

export interface NearbyShop {
  name: string;
  kind: string;
  latitude: number;
  longitude: number;
  distanceM: number | null;
  brand: string | null;
  openingHours: string | null;
}

export interface NearbyShops {
  items: NearbyShop[];
  /**
   * **False means nobody could be asked**, not that the area has no
   * shops. The directory upstream is a free service that is often
   * overloaded, and the screen has to say which of those happened.
   */
  reachable: boolean;
  /** Required wherever this data is shown. */
  attribution: string;
  note: string | null;
}

/** Why a lookup could not happen, in words the screen can show. */
export type ShopsRefusal =
  | 'needsPermission'
  | 'needsConsent'
  | 'noPosition'
  | 'failed';

export class ShopsUnavailable extends Error {
  constructor(readonly reason: ShopsRefusal) {
    super(reason);
    this.name = 'ShopsUnavailable';
  }
}

export function useNearbyShops() {
  return useMutation<NearbyShops, ShopsUnavailable, { radiusM?: number }>({
    mutationFn: async ({ radiusM } = {}) => {
      // Asked at the point of use. A permission prompt that appears
      // because a screen mounted is a prompt nobody understands.
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== Location.PermissionStatus.GRANTED) {
        throw new ShopsUnavailable('needsPermission');
      }

      let here: Location.LocationObject;
      try {
        here = await Location.getCurrentPositionAsync({
          // Coarse on purpose: the server rounds to a kilometre
          // anyway, and asking the device for a precise fix spends
          // battery to produce digits that are thrown away.
          accuracy: Location.Accuracy.Low,
        });
      } catch {
        throw new ShopsUnavailable('noPosition');
      }

      const { data, error, response } = await api.GET('/v1/shops/nearby', {
        params: {
          query: {
            lat: here.coords.latitude,
            lon: here.coords.longitude,
            ...(radiusM ? { radius_m: radiusM } : {}),
          },
        },
      });
      if (error || !data) {
        // The server distinguishes "you have not agreed to this"
        // from everything else, and the screen should offer the
        // switch rather than an error.
        throw new ShopsUnavailable(
          response?.status === 403 ? 'needsConsent' : 'failed',
        );
      }

      const body = data as never as {
        items: {
          name: string;
          kind: string;
          latitude: number;
          longitude: number;
          distance_m: number | null;
          brand: string | null;
          opening_hours: string | null;
        }[];
        reachable: boolean;
        attribution: string;
        note: string | null;
      };
      return {
        items: (body.items ?? []).map((s) => ({
          name: s.name,
          kind: s.kind,
          latitude: s.latitude,
          longitude: s.longitude,
          distanceM: s.distance_m ?? null,
          brand: s.brand ?? null,
          openingHours: s.opening_hours ?? null,
        })),
        reachable: body.reachable ?? true,
        attribution: body.attribution,
        note: body.note ?? null,
      };
    },
  });
}

/** How far away a shop is, as somebody would say it. */
export function howFar(metres: number | null): string {
  if (metres === null) return '';
  if (metres < 1000) return `${Math.round(metres / 50) * 50} m`;
  return `${(metres / 1000).toFixed(metres < 10_000 ? 1 : 0)} km`;
}

/** What to say when there is nothing to show, by reason. */
export function shopsNote(
  refusal: ShopsRefusal | null,
  result: NearbyShops | null,
): string | null {
  if (refusal === 'needsPermission') {
    return 'Allow location and I can show shops near you.';
  }
  if (refusal === 'needsConsent') {
    return 'Turn on coarse location in Settings to see shops near you.';
  }
  if (refusal === 'noPosition') {
    return 'I could not work out where you are just now.';
  }
  if (refusal === 'failed') return 'That did not work. Try again in a moment.';
  if (result && !result.reachable) {
    // Not "there are no shops near you", which is a different and
    // much worse thing to tell somebody.
    return result.note ?? 'The shop directory is not answering just now.';
  }
  if (result && result.items.length === 0) {
    return 'No clothes shops listed near you.';
  }
  return null;
}
