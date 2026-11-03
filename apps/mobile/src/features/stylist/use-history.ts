import { useCallback, useEffect, useRef, useState } from 'react';

import type { Turn } from '@/features/stylist/conversation';
import { ChatHistory, type Session } from '@/features/stylist/history';

/**
 * The stylist's memory, as a hook.
 *
 * One database for the process, opened on first use. `ChatHistory`
 * owns the SQL; this owns *when* a conversation is written, which is
 * the part with a judgement in it.
 *
 * **Saved on a pause, not on every token.** A reply streams in word by
 * word, and writing the whole thread on each one would be a few
 * hundred transactions for one answer. Waiting for the stream to
 * finish instead would lose everything if the app were killed
 * mid-answer, which is exactly when somebody has been waiting. A short
 * debounce keeps both: at most one write per `SETTLE`, and the last
 * state always reaches disk.
 */

/** How long to wait for the stream to go quiet before writing. */
const SETTLE = 600;

export interface HistoryHandle {
  /** The conversation being shown. */
  sessionId: string;
  /** Every conversation, most recent first. Reloaded as they change. */
  sessions: Session[];
  /** True until the first read of the database has finished. */
  loading: boolean;
  /** Turns restored for `sessionId`, or null before they have loaded. */
  restored: readonly Turn[] | null;
  /** Record the current thread under the current session. */
  remember: (turns: readonly Turn[]) => void;
  /** Start an empty conversation and show it. */
  startNew: () => void;
  /** Show an earlier conversation, with its turns. */
  resume: (sessionId: string) => Promise<readonly Turn[]>;
  /** Forget one, or all of them. */
  forget: (sessionId: string) => Promise<void>;
  forgetAll: () => Promise<void>;
}

function freshId(): string {
  // Good enough for a local row id, and no dependency for it.
  return `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export function useChatHistory(): HistoryHandle {
  const store = useRef<ChatHistory | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<readonly Turn[] | null>(null);

  const [sessionId, setSessionId] = useState<string>(freshId);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [restored, setRestored] = useState<readonly Turn[] | null>(null);

  const refresh = useCallback(async () => {
    const db = store.current;
    if (!db) return;
    setSessions(await db.sessions());
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const db = await ChatHistory.open();
        if (!alive) return;
        store.current = db;
        setSessions(await db.sessions());
      } catch {
        // A device whose local database will not open still gets a
        // working assistant; it simply does not remember. Failing the
        // whole wardrobe tab over the history list would be the wrong
        // trade.
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  // Flush whatever is pending when the component goes away, so the
  // last thing said is not lost to the debounce.
  useEffect(
    () => () => {
      const db = store.current;
      const turns = pending.current;
      if (db && turns && turns.length) void db.save(sessionId, turns);
    },
    [sessionId],
  );

  const remember = useCallback(
    (turns: readonly Turn[]) => {
      pending.current = turns;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        const db = store.current;
        if (!db || !turns.length) return;
        void db.save(sessionId, turns).then(refresh);
      }, SETTLE);
    },
    [sessionId, refresh],
  );

  const startNew = useCallback(() => {
    pending.current = null;
    if (timer.current) clearTimeout(timer.current);
    setSessionId(freshId());
    setRestored([]);
  }, []);

  const resume = useCallback(async (id: string) => {
    const db = store.current;
    if (!db) return [];
    const turns = await db.turns(id);
    pending.current = null;
    if (timer.current) clearTimeout(timer.current);
    setSessionId(id);
    setRestored(turns);
    return turns;
  }, []);

  const forget = useCallback(
    async (id: string) => {
      const db = store.current;
      if (!db) return;
      await db.forget(id);
      await refresh();
      if (id === sessionId) {
        setSessionId(freshId());
        setRestored([]);
      }
    },
    [sessionId, refresh],
  );

  const forgetAll = useCallback(async () => {
    const db = store.current;
    if (!db) return;
    await db.forgetAll();
    await refresh();
    setSessionId(freshId());
    setRestored([]);
  }, [refresh]);

  return {
    sessionId,
    sessions,
    loading,
    restored,
    remember,
    startNew,
    resume,
    forget,
    forgetAll,
  };
}
