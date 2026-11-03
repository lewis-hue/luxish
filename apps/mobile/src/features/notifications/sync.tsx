/**
 * Keeps the device's scheduled reminders agreeing with the planner.
 *
 * A component rather than a hook call in the root layout, for the same
 * reason `ReconcileSaved` is: it must sit inside the `QueryClientProvider`
 * to read anything, and the root must not re-render when a background
 * reconcile finishes.
 */

import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

import { announceDevice } from '@/api/queries/devices';
import { useNotificationPrefs } from '@/api/queries/notification-prefs';
import { addDays, isoDay, usePlanner } from '@/api/queries/planner';
import { useAuth } from '@/features/auth/session';
import { ensureChannel, permissionState } from '@/features/notifications/permission';
import { reconcilePlanReminders } from '@/features/notifications/plan-reminders';
import { routeFor } from '@/features/notifications/routing';

/**
 * How a notification arriving while the app is open presents itself.
 *
 * Into the list, never a banner over the app: the one thing this app
 * schedules is a morning line about a plan, and if the planner is already
 * on screen a banner about it is the app interrupting itself. Set once, at
 * module scope, before anything can arrive.
 */
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: false,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

/**
 * Tells the server where this phone is, so it can be reached.
 *
 * **Nothing did this outside the settings screen.** `announceDevice`
 * says in its own docstring that it is safe to call on every launch,
 * and the only two callers were both inside
 * `notification-settings.tsx` - behind a permission grant somebody
 * had to go looking for. So anybody who allowed notifications once
 * and never opened that screen again had no device row on the server,
 * and every notification queued for them was dropped at the gateway
 * with "No device registered for this account." The notification was
 * written, batched, scheduled and thrown away.
 *
 * **It never asks.** Asking is a decision the settings screen makes,
 * with a sentence explaining why. This only acts on an answer already
 * given: granted means register, anything else means do nothing. A
 * permission prompt appearing unprompted at launch is exactly how
 * somebody decides to say no.
 *
 * **On foreground as well as on sign-in**, because both change the
 * answer without this component rendering again: a token can be
 * reissued after a reinstall or a restore, and permission is often
 * granted in the system settings app, which happens while this one is
 * in the background. `announceDevice` remembers the last token it
 * sent, so the repeat calls cost nothing.
 */
export function DeviceRegistration() {
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  useEffect(() => {
    if (!signedIn) return;

    let live = true;
    const announce = async () => {
      if ((await permissionState()) !== 'granted') return;
      // The Android channel has to exist before a notification can be
      // shown on it, and this is the earliest point it is known to be
      // wanted.
      await ensureChannel();
      if (live) void announceDevice();
    };

    void announce();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void announce();
    });
    return () => {
      live = false;
      subscription.remove();
    };
  }, [signedIn]);

  return null;
}

/**
 * Opens the screen a tapped notification is about.
 *
 * **Nothing listened for a tap before this.** A notification opened
 * the app on whatever screen it was last on, which for anything that
 * finished while the app was closed means the notice tells you
 * something is ready and then does not take you to it.
 *
 * Two entry points, because a tap arrives differently depending on
 * what the app was doing. `useLastNotificationResponse` covers the
 * cold start - the app was not running, and the tap is what launched
 * it - and the listener covers a tap while it is open or in the
 * background. Both land in `routeFor`, so there is one rule.
 *
 * Only while signed in: the routes are all behind the auth guard, and
 * pushing one from a signed-out app is a redirect to the welcome
 * screen with a confusing history behind it.
 */
export function NotificationRouting() {
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const launched = Notifications.useLastNotificationResponse();
  /** Responses are replayed on mount, so each is acted on once. */
  const handled = useRef<string | null>(null);

  useEffect(() => {
    if (!signedIn) return;

    const open = (response: Notifications.NotificationResponse) => {
      const id = response.notification.request.identifier;
      if (handled.current === id) return;
      handled.current = id;
      const data = response.notification.request.content.data as
        | Record<string, unknown>
        | undefined;
      router.push(
        routeFor({
          named:
            typeof data?.deep_link === 'string'
              ? data.deep_link
              : typeof data?.target === 'string'
                ? data.target
                : null,
          kind: typeof data?.kind === 'string' ? data.kind : null,
        }) as never,
      );
    };

    if (launched) open(launched);
    const subscription =
      Notifications.addNotificationResponseReceivedListener(open);
    return () => subscription.remove();
  }, [signedIn, launched]);

  return null;
}

export function PlanReminders() {
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const prefs = useNotificationPrefs(signedIn);

  // The week the planner itself shows. The strings are stable within a
  // day, so the query key only rolls at midnight.
  const today = new Date();
  const start = isoDay(today);
  const end = isoDay(addDays(today, 7));
  const wantReminders = signedIn && (prefs.data?.planReminders ?? false);
  const plans = usePlanner(start, end, wantReminders);

  useEffect(() => {
    if (!signedIn || !prefs.data) return;
    void (async () => {
      // Never prompts. If permission has not been granted the schedule is
      // left alone; the settings screen is where the prompt is spent, next
      // to the words that say what it is for.
      const state = await permissionState();
      if (state !== 'granted') return;
      await ensureChannel();
      await reconcilePlanReminders({
        enabled: prefs.data.planReminders,
        plans: plans.data ?? [],
      });
    })();
  }, [signedIn, prefs.data, plans.data]);

  return null;
}
