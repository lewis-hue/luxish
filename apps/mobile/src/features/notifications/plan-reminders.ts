/**
 * A quiet line on the morning of a planned outfit.
 *
 * **Local, and honestly so.** These are scheduled on this device out of the
 * planner; no server sends them, so they work in Expo Go, offline, and
 * before any push credential exists. The cost of that honesty is the usual
 * one for local scheduling: a plan made on another device is not known here
 * until this one next opens the app.
 *
 * **Reconciled, never appended.** Every sync cancels the reminders this
 * module owns and schedules the current week fresh. Appending instead would
 * double a reminder each time a plan was edited, and a cancelled plan would
 * keep its ghost. Ownership is marked in the payload (`kind`), so nothing
 * else this app ever schedules can be swept up by the cancel.
 */

import * as Notifications from 'expo-notifications';


/** The payload marker that makes a scheduled notification ours to cancel. */
const KIND = 'plan_reminder';

/** When the line arrives: early enough to matter while dressing. */
const HOUR = 7;
const MINUTE = 30;

/** How far ahead to schedule. The planner is a week view; so is this. */
const DAYS_AHEAD = 7;

export interface PlanLike {
  /** `YYYY-MM-DD`, a day in the wearer's calendar. */
  plannedFor: string;
  /** The clothes laid out for it, from this person's wardrobe. */
  garmentIds: readonly string[];
  note: string | null;
}

export interface Reminder {
  date: Date;
  title: string;
  body: string;
  /** How many pieces are laid out, for the screen that lists these. */
  pieces: number;
}

/**
 * The reminders a set of plans deserves, pure and testable.
 *
 * One per plan, at 07:30 local on the planned day, skipping anything whose
 * moment has already passed: a reminder for this morning scheduled this
 * afternoon would fire immediately, which is noise about the past.
 */
export function remindersFor(plans: readonly PlanLike[], now: Date): Reminder[] {
  const horizon = new Date(now);
  horizon.setDate(horizon.getDate() + DAYS_AHEAD);

  const out: Reminder[] = [];
  for (const plan of plans) {
    const [year, month, day] = plan.plannedFor.split('-').map(Number);
    if (!year || !month || !day) continue;
    const at = new Date(year, month - 1, day, HOUR, MINUTE, 0, 0);
    if (at <= now || at > horizon) continue;

    // Nothing laid out is nothing to remind anybody about. A plan
    // can exist with a note and no clothes while somebody is still
    // choosing, and a notification about an empty day is noise.
    const pieces = plan.garmentIds.length;
    if (pieces === 0) continue;
    out.push({
      date: at,
      title: 'Your plan for today',
      body:
        plan.note?.trim() ||
        (pieces === 1 ? '1 piece laid out.' : `${pieces} pieces laid out.`),
      pieces,
    });
  }
  return out.sort((a, b) => a.date.getTime() - b.date.getTime());
}

/**
 * Make the device's schedule match the given plans.
 *
 * With `enabled` false it only clears, which is what turning the toggle
 * off must mean: no ghost reminders from when it was on.
 */
export async function reconcilePlanReminders(input: {
  enabled: boolean;
  plans: readonly PlanLike[];
  now?: Date;
}): Promise<number> {
  const scheduled = await Notifications.getAllScheduledNotificationsAsync();
  await Promise.all(
    scheduled
      .filter((item) => item.content.data?.kind === KIND)
      .map((item) => Notifications.cancelScheduledNotificationAsync(item.identifier)),
  );

  if (!input.enabled) return 0;

  const reminders = remindersFor(input.plans, input.now ?? new Date());
  await Promise.all(
    reminders.map((reminder) =>
      Notifications.scheduleNotificationAsync({
        content: {
          title: reminder.title,
          body: reminder.body,
          data: { kind: KIND, url: '/planner' },
        },
        trigger: {
          type: Notifications.SchedulableTriggerInputTypes.DATE,
          date: reminder.date,
          channelId: 'plans',
        },
      }),
    ),
  );
  return reminders.length;
}
