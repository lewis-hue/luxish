/**
 * Asking the stylist for an outfit, and waiting for the answer.
 *
 * Two calls, because that is what the work is. Styling calls a model, reads a
 * whole wardrobe and re-validates every garment it is handed back, which takes
 * seconds; holding an HTTP request open for that would make a slow network
 * indistinguishable from a broken one. So the server accepts the request, the
 * client polls, and a backgrounded app can pick the run up again by its id.
 *
 * Nothing here invents an outfit. If the run fails, or finds nothing it can
 * build from the clothes someone owns, that is the answer and it is reported
 * as such — a stylist that quietly suggests things you do not have is worse
 * than one that says it cannot.
 */

import { api, ApiError } from '@/api/client';
import { accessToken } from '@/features/auth/session';

/**
 * The states the server calls finished.
 *
 * Taken from the server's own `TERMINAL_RUN_STATES` rather than guessed: a
 * successful run reports `completed`, not `succeeded`, and a client polling
 * for the wrong word waits out its whole budget on a run that finished in
 * seconds, then reports a timeout for an outfit that is sitting there.
 */
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

export class NotSignedIn extends Error {
  constructor() {
    super('Sign in to use the stylist.');
    this.name = 'NotSignedIn';
  }
}

export interface OutfitPiece {
  role: string;
  /** True when this is a garment the user already owns. */
  owned: boolean;
  garmentId: string | null;
  name: string | null;
  category: string | null;
}

export interface StylistOutcome {
  runId: string;
  state: string;
  outfit: {
    id: string;
    pieces: readonly OutfitPiece[];
    rationale: string | null;
    /** Slots the stylist could not fill from the wardrobe. */
    missingSlots: readonly string[];
  } | null;
  /** Why there is no outfit, in words meant for a person. */
  explanation: string | null;
  explanationCode: string | null;
}

/**
 * True when the run did something other than build an outfit.
 *
 * The assistant is one input box: asking it to photograph a piece or make
 * a set of brand visuals is a sentence, not a button, so a run can come
 * back having started a shoot. Those answers are not "no outfit found" and
 * must not be shown as a failure.
 */
export function isAssistantAnswer(outcome: StylistOutcome | null): boolean {
  return Boolean(outcome?.explanationCode?.startsWith('assistant_'));
}

/**
 * Start a run. Returns its id; the answer arrives through {@link awaitRun}.
 *
 * The subject ids travel with the request because what can be asked for
 * depends on what is in hand: a garment can be photographed, a published
 * fit can be worn. The server decides which of those the sentence meant,
 * and re-validates every id against the asker before acting on it.
 */
export async function startRun(input: {
  text: string;
  occasion?: string | null;
  garmentId?: string | null;
  mediaAssetId?: string | null;
  postId?: string | null;
}): Promise<string> {
  if (!(await accessToken())) throw new NotSignedIn();

  const started = await api.POST('/v1/stylist/runs', {
    body: {
      text: input.text.trim() || null,
      occasion: input.occasion?.trim() || null,
      garment_id: input.garmentId || null,
      media_asset_id: input.mediaAssetId || null,
      post_id: input.postId || null,
    },
  });
  if (started.error || !started.data) {
    throw new Error('The stylist could not take that request.');
  }
  return started.data.run_id;
}

/**
 * Poll until the run reaches a terminal state.
 *
 * The budget is set from a measured run, not a guess. Styling is a bounded
 * loop: the model calls tools, the server re-validates every garment it is
 * handed, and a rejected plan is sent back for another attempt. A real run
 * against a 28-garment wardrobe took **155 seconds**, so a one-minute budget
 * would have reported a timeout for an outfit that was already finished.
 *
 * The interval is unhurried for the same reason. Asking every 200ms would
 * spend requests watching a number that changes far more slowly than that.
 */
export async function awaitRun(
  runId: string,
  options: { attempts?: number; intervalMs?: number } = {},
): Promise<StylistOutcome> {
  const attempts = options.attempts ?? 120;
  const intervalMs = options.intervalMs ?? 2000;

  let last: StylistOutcome | null = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const read = await api.GET('/v1/stylist/runs/{run_id}', {
      params: { path: { run_id: runId } },
    });
    if (read.error || !read.data) {
      throw new Error('Could not read the styling run.');
    }

    last = toOutcome(runId, read.data as Record<string, unknown>);
    if (TERMINAL.has(last.state)) return last;

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  // Ran out of patience, not out of hope: the run is still on the server and
  // can be read again by its id.
  throw new Error('The stylist is taking longer than usual. Try again shortly.');
}

function toOutcome(runId: string, data: Record<string, unknown>): StylistOutcome {
  const outfit = data.outfit as Record<string, unknown> | null | undefined;
  const items = (outfit?.items ?? []) as Record<string, unknown>[];

  return {
    runId,
    state: String(data.state ?? 'running'),
    outfit: outfit
      ? {
          id: String(outfit.id ?? ''),
          pieces: items.map((item) => ({
            role: String(item.role ?? ''),
            owned: Boolean(item.owned),
            garmentId: (item.garment_id as string | null) ?? null,
            name: (item.name as string | null) ?? null,
            category: (item.category as string | null) ?? null,
          })),
          rationale: (outfit.rationale as string | null) ?? null,
          missingSlots: (outfit.missing_slots ?? []) as string[],
        }
      : null,
    explanation: (data.explanation as string | null) ?? null,
    explanationCode: (data.explanation_code as string | null) ?? null,
  };
}

/** Turns anything thrown here into something a screen can show a person. */
export function describeRunFailure(error: unknown): { title: string; body: string } {
  if (error instanceof NotSignedIn) {
    return {
      title: 'Sign in to use the stylist',
      body: 'Styling runs on the server so it can see your whole wardrobe.',
    };
  }
  if (error instanceof ApiError && error.status === 401) {
    return {
      title: 'Your session ended',
      body: 'Sign in again and the request will be waiting.',
    };
  }
  if (error instanceof ApiError && error.status === 429) {
    return {
      title: 'Too many requests',
      body: 'Give it a moment and ask again.',
    };
  }
  return {
    title: 'The stylist could not finish',
    body: error instanceof Error ? error.message : 'Try again shortly.',
  };
}
