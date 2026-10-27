import Store from 'expo-sqlite/kv-store';
import { useCallback, useEffect, useState } from 'react';

/**
 * What people actually do with a look, and what "trending" is allowed to mean.
 *
 * §1 asks for trending pins "measured according to the current trending styles and
 * how users have interacted or asked about such items". The second half is the part
 * worth being careful about: a trending score is a claim about *other people*, and
 * this app currently has no view of other people. There is no authenticated session,
 * so no events reach the server, so nothing here can honestly describe a population.
 *
 * So this module does the half that is real now — capture the events, locally,
 * with the shape the aggregation endpoint will accept — and computes a score
 * labelled for exactly what it is: **this device**. The UI says "Popular with you",
 * never "Trending", until the server is aggregating. Inventing a global trend from
 * one person's taps would be a fabrication that looks like a feature.
 *
 * Weights reflect intent, not just attention. Asking the stylist about a look is a
 * much stronger signal than scrolling past it, and saving it is stronger still —
 * someone expects to come back to it.
 */

const KEY = 'fashion.look_interactions';

/** Ordered by how much intent each one demonstrates. */
export type InteractionKind =
  /** The detail screen was opened. Weak — includes curiosity and mistakes. */
  | 'view'
  /** A specific piece was searched for on the web. Strong: they want to own it. */
  | 'search_piece'
  /** The stylist was asked about this look. Strongest short of saving. */
  | 'ask_stylist'
  /** Kept for later. Strongest: they expect to return. */
  | 'save';

const WEIGHTS: Record<InteractionKind, number> = {
  view: 1,
  search_piece: 4,
  ask_stylist: 6,
  save: 8,
};

/**
 * Events older than this stop counting toward the score.
 *
 * Without decay a look you liked once in January outranks what you are into now,
 * which is the opposite of trending.
 */
const WINDOW_DAYS = 30;
const WINDOW_MS = WINDOW_DAYS * 24 * 60 * 60 * 1000;

/** Bounded so the log cannot grow without limit on a device. */
const MAX_EVENTS = 500;

export interface InteractionEvent {
  lookId: string;
  kind: InteractionKind;
  /** Epoch ms. Sent to the server verbatim so ordering survives the upload. */
  at: number;
  /** Carried so the server can aggregate by aesthetic without re-deriving it. */
  aesthetics: readonly string[];
}

function read(): InteractionEvent[] {
  try {
    const raw = Store.getItemSync(KEY);
    return raw ? (JSON.parse(raw) as InteractionEvent[]) : [];
  } catch {
    return [];
  }
}

async function write(events: InteractionEvent[]): Promise<void> {
  await Store.setItemAsync(KEY, JSON.stringify(events.slice(-MAX_EVENTS)));
}

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

/** Records one event. Fire-and-forget: never block a tap on analytics. */
export async function recordInteraction(
  lookId: string,
  kind: InteractionKind,
  aesthetics: readonly string[] = [],
  now: number = Date.now(),
): Promise<void> {
  const events = read();
  events.push({ lookId, kind, at: now, aesthetics });
  await write(events);
  notify();
}

export interface Popularity {
  lookId: string;
  score: number;
  /** Distinct kinds seen, so the UI can say *why* something ranks. */
  signals: readonly InteractionKind[];
}

/**
 * Ranks looks by this device's own activity.
 *
 * Pure and time-injectable so the decay is testable rather than asserted.
 */
export function rank(
  events: readonly InteractionEvent[],
  now: number = Date.now(),
): readonly Popularity[] {
  const cutoff = now - WINDOW_MS;
  const totals = new Map<string, { score: number; signals: Set<InteractionKind> }>();

  for (const event of events) {
    if (event.at < cutoff) continue;

    // Linear decay across the window: an event today counts fully, one at the
    // edge counts for almost nothing.
    const freshness = 1 - (now - event.at) / WINDOW_MS;
    const entry = totals.get(event.lookId) ?? { score: 0, signals: new Set() };
    entry.score += WEIGHTS[event.kind] * Math.max(freshness, 0);
    entry.signals.add(event.kind);
    totals.set(event.lookId, entry);
  }

  return [...totals.entries()]
    .map(([lookId, entry]) => ({
      lookId,
      score: Math.round(entry.score * 10) / 10,
      signals: [...entry.signals],
    }))
    .sort((a, b) => b.score - a.score);
}

export function usePopularLooks() {
  const [events, setEvents] = useState<InteractionEvent[]>(() => read());

  useEffect(() => {
    const listener = () => setEvents(read());
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const record = useCallback(
    (lookId: string, kind: InteractionKind, aesthetics: readonly string[] = []) => {
      void recordInteraction(lookId, kind, aesthetics);
    },
    [],
  );

  return {
    /** Ranked by this device's activity. Never present this as a global trend. */
    popular: rank(events),
    record,
    /**
     * False until the server aggregates across users. The UI reads this to pick
     * its label, so the honest wording is enforced in one place rather than
     * remembered at each call site.
     */
    isGlobalTrend: false as const,
    eventCount: events.length,
  };
}

/** The pending events, for upload once there is a session to attach them to. */
export function pendingInteractions(): readonly InteractionEvent[] {
  return read();
}

export const INTERACTION_WEIGHTS = WEIGHTS;
export const INTERACTION_WINDOW_DAYS = WINDOW_DAYS;
