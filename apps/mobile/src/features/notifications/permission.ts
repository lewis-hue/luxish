/**
 * The one notification permission, asked for once and never wasted.
 *
 * iOS records the first answer forever: a second `requestPermissionsAsync`
 * is a silent no-op that returns the stored verdict, so the prompt must
 * only ever be spent on somebody who has just been told what it is for.
 * Android 13+ can re-ask, but the same courtesy applies.
 *
 * Everything here is local-notification territory. Remote push needs store
 * credentials this project does not hold yet (APNs key, Firebase project),
 * and nothing in this module pretends otherwise.
 */

import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { AndroidImportance, IosAuthorizationStatus } from 'expo-notifications';
import { Linking, Platform } from 'react-native';

export type PermissionState =
  | 'undetermined'
  | 'granted'
  | 'denied'
  /** Denied, and the OS will not show the prompt again. Settings is the
   *  only door left, so the UI must offer it rather than a dead button. */
  | 'blocked';

/** Where things stand, with no user-facing effect. Safe to call on mount. */
export async function permissionState(): Promise<PermissionState> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return 'granted';
  // Provisional iOS authorisation counts as granted for local notifications:
  // they deliver, quietly, which is all the planner reminder needs.
  if (
    current.ios?.status === IosAuthorizationStatus.PROVISIONAL
  ) {
    return 'granted';
  }
  if (current.status === 'undetermined') return 'undetermined';
  return current.canAskAgain ? 'denied' : 'blocked';
}

/**
 * Spend the prompt. Only call this from an explicit tap on a control that
 * said what notifications are for; never from an effect.
 */
export async function requestPermission(): Promise<PermissionState> {
  const result = await Notifications.requestPermissionsAsync();
  if (result.granted) return 'granted';
  if (result.status === 'undetermined') return 'undetermined';
  return result.canAskAgain ? 'denied' : 'blocked';
}

/** The system settings page for this app, for the `blocked` state. */
export function openSystemSettings(): void {
  void Linking.openSettings();
}

/**
 * The Android channel plan reminders arrive on.
 *
 * Created before anything schedules: Android 13 will not even show the
 * permission prompt until a channel exists, and the fallback channel
 * expo-notifications creates otherwise is named "Miscellaneous" in the
 * system settings, which is nobody's brand.
 */
export async function ensureChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync('plans', {
    name: 'Plan reminders',
    importance: AndroidImportance.DEFAULT,
  });
}

/**
 * This installation's push token, or null when one cannot be had.
 *
 * **Null is the normal answer today, and that is not a bug.** An Expo
 * push token needs an EAS project id in the app config, and remote
 * push does not work in Expo Go on Android at all since SDK 53. The
 * server side of notifications is built and tested; this is the half
 * that waits on a linked EAS project and a development build.
 *
 * Returning null rather than throwing is deliberate: registering a
 * device is something the app does quietly in the background, and a
 * missing credential must never surface as an error to somebody who
 * only turned a switch on.
 */
export async function pushToken(): Promise<string | null> {
  const projectId =
    Constants.expoConfig?.extra?.eas?.projectId ??
    Constants.easConfig?.projectId ??
    null;
  if (!projectId) {
    if (__DEV__) {
      console.info(
        '[notifications] no EAS project id, so no push token. ' +
          'Run `eas init` and use a development build to enable this.',
      );
    }
    return null;
  }
  try {
    const got = await Notifications.getExpoPushTokenAsync({ projectId });
    return got.data ?? null;
  } catch (caught) {
    if (__DEV__) console.warn('[notifications] could not get a token', caught);
    return null;
  }
}

/** The phone's own zone, so the server does not wake somebody at 3am. */
export function deviceTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}
