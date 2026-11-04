import { fetch as streamingFetch } from 'expo/fetch';

import { API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

/**
 * Asking the stylist a question, and reading the answer as it is written.
 *
 * **Why not the generated client.** `openapi-fetch` resolves the whole
 * body before it hands anything back, which is the one thing this
 * endpoint exists to avoid: the server streams so the first words
 * reach the screen while the rest is still being written. `expo/fetch`
 * is the React Native fetch that exposes a readable body, so this uses
 * it directly and parses the events itself.
 *
 * **Why this is not the run flow.** `startRun`/`awaitRun` queue work
 * and poll for a picture, which is right for a 20-second render and
 * wrong for a sentence. A question gets answered; only what follows
 * from the answer gets queued.
 */

/** What the server sends, one JSON object per SSE frame. */
export type AskEvent =
  | { event: 'token'; text: string }
  | { event: 'verdict'; has_match: boolean; using: string[]; missing: string[] }
  | { event: 'shopping'; items: ShoppableItem[] }
  | { event: 'pieces'; items: GapPicture[] }
  | { event: 'render'; render_id: string }
  | { event: 'done' }
  | { event: 'error' };

/**
 * A picture of a garment they do not own, so the look can be shown
 * rather than only described.
 *
 * Drawn once per phrase on the server and shared by every account,
 * so this is usually a row lookup. `state` is `queued` the first
 * time anybody asks for a given garment and `ready` thereafter;
 * the thread polls until it turns.
 */
export interface GapPicture {
  phrase: string;
  slot: string | null;
  state: 'queued' | 'ready' | 'failed';
  asset_id: string | null;
}

export interface ShoppableItem {
  product_id: string;
  title: string | null;
  retailer: string | null;
  url: string | null;
  match_label: string | null;
}

export interface AskHandlers {
  /** A new piece of the sentence. Append it; never replace. */
  onToken?: (text: string) => void;
  onVerdict?: (verdict: {
    hasMatch: boolean;
    using: string[];
    missing: string[];
  }) => void;
  onShopping?: (items: ShoppableItem[]) => void;
  /** Pictures for the pieces they would need. */
  onPieces?: (items: GapPicture[]) => void;
  /** An avatar has been queued. Poll for it as usual. */
  onRender?: (renderId: string) => void;
  onError?: () => void;
}

/**
 * Ask, and call back as the answer arrives. Resolves when it is done.
 *
 * `signal` aborts it, which matters because somebody can leave the
 * screen mid-sentence and a stream nobody is reading is a connection
 * held open for nothing.
 */
export async function askStylist(
  input: {
    question: string;
    postId?: string | null;
    /**
     * What has already been said, oldest first.
     *
     * Sent by the client rather than kept on the server: it is a
     * few turns about one wardrobe, it ends when the screen closes,
     * and storing it would mean a table, a retention rule and an
     * export entry for something nobody asked to keep.
     */
    history?: { who: 'you' | 'stylist'; text: string }[];
  },
  handlers: AskHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  const token = await accessToken();
  if (!token) {
    handlers.onError?.();
    return;
  }

  let response: Awaited<ReturnType<typeof streamingFetch>>;
  try {
    response = await streamingFetch(`${API_BASE_URL}/v1/stylist/ask`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        question: input.question,
        post_id: input.postId ?? null,
        history: input.history ?? [],
      }),
      signal,
    });
  } catch {
    handlers.onError?.();
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError?.();
    return;
  }

  const reader = response.body.getReader();
  const decode = new TextDecoder();
  // Frames are split on a blank line and a chunk boundary lands
  // anywhere, so whatever is after the last blank line is held back
  // until the rest of it arrives.
  let pending = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      pending += decode.decode(value, { stream: true });

      const frames = pending.split('\n\n');
      // The last piece is either empty or a half-arrived frame.
      pending = frames.pop() ?? '';
      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith('data:')) continue;
        let parsed: AskEvent;
        try {
          parsed = JSON.parse(line.slice(5).trim()) as AskEvent;
        } catch {
          // One unreadable frame is not a failed answer.
          continue;
        }
        deliver(parsed, handlers);
      }
    }
  } catch {
    // An aborted read is the normal way this ends when somebody
    // leaves the screen, so it is not reported as a failure.
    if (!signal?.aborted) handlers.onError?.();
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Already released by an abort.
    }
  }
}

function deliver(parsed: AskEvent, handlers: AskHandlers): void {
  switch (parsed.event) {
    case 'token':
      handlers.onToken?.(parsed.text);
      break;
    case 'verdict':
      handlers.onVerdict?.({
        hasMatch: parsed.has_match,
        using: parsed.using ?? [],
        missing: parsed.missing ?? [],
      });
      break;
    case 'shopping':
      handlers.onShopping?.(parsed.items ?? []);
      break;
    case 'pieces':
      handlers.onPieces?.(parsed.items ?? []);
      break;
    case 'render':
      handlers.onRender?.(parsed.render_id);
      break;
    case 'error':
      handlers.onError?.();
      break;
    case 'done':
      break;
  }
}

/** The line shown while nothing has arrived yet. */
export const THINKING = 'Looking through your wardrobe';
