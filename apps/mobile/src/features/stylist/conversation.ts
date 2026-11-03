/**
 * The stylist conversation, as a list of turns.
 *
 * **Why this replaces a single result slot.** The panel held one
 * outcome at a time: you asked, it answered, and asking again threw
 * the previous answer away. That is a form, not a conversation, and
 * it made the obvious follow-ups impossible - "what about with the
 * boots instead", "show me that on me" - because the thing being
 * referred to had already been cleared off the screen.
 *
 * Everything the stylist produces is a turn, including a picture. An
 * avatar wearing an outfit is an answer to "show me that on me", so
 * it belongs in the thread beside the sentence that led to it rather
 * than in a panel of its own. That is also what lets somebody keep
 * talking after seeing it.
 *
 * Pure and reducer-shaped on purpose: a chat whose state only exists
 * inside a component is a chat nobody can test.
 */

export type Who = 'you' | 'stylist';

export interface Verdict {
  hasMatch: boolean;
  using: string[];
  missing: string[];
}

export interface Shoppable {
  product_id: string;
  title: string | null;
  retailer: string | null;
  url: string | null;
  match_label: string | null;
}

export interface Turn {
  id: string;
  who: Who;
  text: string;
  /** True while the words are still arriving. */
  streaming?: boolean;
  /** Set once the structured half of a reply has landed. */
  verdict?: Verdict;
  shopping?: Shoppable[];
  /**
   * An avatar queued for this turn. The picture appears in the
   * thread when it is ready, which is what makes a try-on part of
   * the conversation rather than a separate screen.
   */
  renderId?: string;
  /* The picture itself is not mirrored here. `renderId` is the
     handle; the thread looks the render up in the list that polls
     them, so there is one answer to "is it drawn yet" rather than a
     copy that can fall behind. */
  failed?: boolean;
}

export interface Conversation {
  turns: Turn[];
  /** Incremented so every turn gets a stable key without a uuid. */
  next: number;
}

export const EMPTY: Conversation = { turns: [], next: 1 };

export function begin(): Conversation {
  return EMPTY;
}

/** What the person just said, plus the empty reply it is waiting for. */
export function asked(state: Conversation, text: string): Conversation {
  const said = text.trim();
  if (!said) return state;
  return {
    next: state.next + 2,
    turns: [
      ...state.turns,
      { id: `t${state.next}`, who: 'you', text: said },
      { id: `t${state.next + 1}`, who: 'stylist', text: '', streaming: true },
    ],
  };
}

/** Append arriving words to the reply being written. */
export function streamed(state: Conversation, chunk: string): Conversation {
  return mapLastStylist(state, (turn) => ({
    ...turn,
    text: turn.text + chunk,
  }));
}

export function decided(
  state: Conversation,
  verdict: Verdict,
): Conversation {
  return mapLastStylist(state, (turn) => ({ ...turn, verdict }));
}

export function shopped(
  state: Conversation,
  shopping: Shoppable[],
): Conversation {
  return mapLastStylist(state, (turn) => ({ ...turn, shopping }));
}

export function drawing(state: Conversation, renderId: string): Conversation {
  return mapLastStylist(state, (turn) => ({ ...turn, renderId }));
}

/** The reply is complete, however it went. */
export function settled(state: Conversation): Conversation {
  return mapLastStylist(state, (turn) => ({
    ...turn,
    streaming: false,
    // A reply that streamed nothing and carries no picture said
    // nothing at all; a blank bubble is worse than a sentence
    // admitting it.
    text:
      turn.text ||
      (turn.renderId
        ? 'Here it is.'
        : 'I could not answer that one. Ask me again?'),
  }));
}

export function failed(state: Conversation): Conversation {
  return mapLastStylist(state, (turn) => ({
    ...turn,
    streaming: false,
    failed: true,
    text: turn.text || 'That did not go through. Try me again in a moment.',
  }));
}

/**
 * The turns to send back as context, oldest first.
 *
 * Only settled text: a half-streamed reply is not something the
 * model said, and sending it back would have it continue its own
 * unfinished sentence.
 */
export function history(
  state: Conversation,
  limit = 10,
): { who: Who; text: string }[] {
  return state.turns
    .filter((turn) => !turn.streaming && turn.text.trim() && !turn.failed)
    .slice(-limit)
    .map((turn) => ({ who: turn.who, text: turn.text }));
}

/** Whether a reply is still being written. */
export function busy(state: Conversation): boolean {
  return state.turns.some((turn) => turn.streaming);
}

/**
 * Whether this turn should offer to put the look on them.
 *
 * Only where there is something to wear and no picture yet. Offering
 * it under "you own nothing for this" with no suggestions would be a
 * button with nothing behind it.
 */
export function canTryOn(turn: Turn): boolean {
  if (turn.who !== 'stylist' || turn.streaming) return false;
  if (turn.renderId) return false;
  const verdict = turn.verdict;
  if (!verdict) return false;
  return verdict.using.length > 0 || verdict.missing.length > 0;
}

function mapLastStylist(
  state: Conversation,
  change: (turn: Turn) => Turn,
): Conversation {
  const at = lastStylistAt(state);
  if (at < 0) return state;
  const turns = state.turns.slice();
  turns[at] = change(turns[at]);
  return { ...state, turns };
}

function lastStylistAt(state: Conversation): number {
  for (let at = state.turns.length - 1; at >= 0; at -= 1) {
    if (state.turns[at].who === 'stylist') return at;
  }
  return -1;
}
