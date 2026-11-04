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

import type { GapPicture } from '@/features/stylist/ask';

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
   * A picture per piece they would need, so an answer they own none
   * of still shows the look instead of only naming it.
   *
   * **The reported failure this fixes.** "How would baggy skater
   * shorts with white sneakers and a white t-shirt look on me?" was
   * answered with three shop links and nothing to look at, while
   * every reply around it carried a figure wearing the look. These
   * go onto the same figure.
   */
  pieces?: GapPicture[];
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
  /**
   * The picture that was sent up with this question.
   *
   * On the turn, not on the composer. The thing being asked about is
   * part of what was asked, so it belongs in the transcript beside
   * the words - and once it is recorded there, the composer can drop
   * it the moment the question is sent. Leaving the card pinned above
   * the box made it look as though every later question was still
   * about that pin, when the model has the whole conversation and
   * does not need it re-sent.
   */
  shownWith?: string;
  /**
   * When it was said, in epoch milliseconds.
   *
   * Stamped on the turn rather than read from the clock at render
   * time, or a conversation restored from history would show every
   * turn as having happened the moment it was reopened.
   */
  at?: number;
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
export function asked(
  state: Conversation,
  text: string,
  /** A thumbnail of whatever went up with it, if anything did. */
  shownWith?: string,
): Conversation {
  const said = text.trim();
  if (!said) return state;
  return {
    next: state.next + 2,
    turns: [
      ...state.turns,
      { id: `t${state.next}`, who: 'you', text: said, shownWith, at: Date.now() },
      {
        id: `t${state.next + 1}`,
        who: 'stylist',
        text: '',
        streaming: true,
        at: Date.now(),
      },
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

export function pictured(
  state: Conversation,
  pieces: GapPicture[],
): Conversation {
  return mapLastStylist(state, (turn) => ({ ...turn, pieces }));
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

/**
 * Remove one of your own questions and the answer it produced.
 *
 * **A question and its reply are one unit.** Deleting the question
 * and leaving the answer under it leaves a reply to nothing, which
 * reads worse than either. The stylist turn immediately after goes
 * with it; anything further down stays, because it was a separate
 * exchange.
 */
export function forget(state: Conversation, turnId: string): Conversation {
  const at = state.turns.findIndex((turn) => turn.id === turnId);
  if (at < 0 || state.turns[at].who !== 'you') return state;
  const next = state.turns[at + 1];
  const drop = next && next.who === 'stylist' ? 2 : 1;
  return {
    ...state,
    turns: [...state.turns.slice(0, at), ...state.turns.slice(at + drop)],
  };
}

/**
 * Take a question back so it can be asked again differently.
 *
 * Everything from that question onward goes, and its words are
 * handed back for the composer. **Everything after, not just the
 * one reply:** the turns below were answers to a conversation whose
 * premise is being changed, and leaving them would make the thread
 * read as though the stylist replied to a question nobody asked.
 */
export function rewind(
  state: Conversation,
  turnId: string,
): { state: Conversation; text: string } {
  const at = state.turns.findIndex((turn) => turn.id === turnId);
  if (at < 0 || state.turns[at].who !== 'you') return { state, text: '' };
  return {
    state: { ...state, turns: state.turns.slice(0, at) },
    text: state.turns[at].text,
  };
}
