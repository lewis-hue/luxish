/**
 * Telling the server where this phone is.
 *
 * **Quiet on every path.** Registering a device is background work
 * nobody asked for directly, so nothing here surfaces an error: a
 * phone that cannot be registered simply does not receive push
 * notifications, which is the same state it was in a moment ago.
 *
 * **Null token is the normal answer today.** See
 * `features/notifications/permission.pushToken` - it needs an EAS
 * project id and a development build. The call is written so that
 * linking the project is the only thing left to do.
 */

import { api } from '@/api/client';
import { deviceTimezone, pushToken } from '@/features/notifications/permission';

/** The last token sent, so a relaunch does not repeat the call. */
let announced: string | null = null;

/**
 * Register this phone, if it has a token to register.
 *
 * Safe to call on every launch and after every permission grant: the
 * server treats the same token as the same device and updates the row
 * rather than adding one.
 */
export async function announceDevice(): Promise<boolean> {
  const token = await pushToken();
  if (!token || token === announced) return false;
  try {
    const { error } = await api.PUT('/v1/push/devices', {
      body: {
        token,
        platform: 'expo',
        timezone: deviceTimezone() ?? undefined,
      },
    });
    if (error) return false;
    announced = token;
    return true;
  } catch {
    return false;
  }
}

/**
 * Stop sending to this phone.
 *
 * Called on sign-out: the account is leaving the device, and the next
 * person to sign in here should not inherit its notifications.
 */
export async function forgetDevice(): Promise<void> {
  const token = announced ?? (await pushToken());
  announced = null;
  if (!token) return;
  try {
    await api.DELETE('/v1/push/devices/{token}', {
      params: { path: { token } },
    });
  } catch {
    // Signing out must not fail because a phone could not be
    // de-registered; the token is revoked on next sign-in anyway.
  }
}
