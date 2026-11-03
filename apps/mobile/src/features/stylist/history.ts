import * as SQLite from 'expo-sqlite';

import type { Turn } from '@/features/stylist/conversation';

/**
 * Conversations with the stylist, kept.
 *
 * **The thread used to live in a `useState` and die with the screen.**
 * Leaving the wardrobe tab threw away everything that had been said,
 * so the assistant could not be asked a follow-up after a glance at
 * Discover, and nothing that had been worked out together survived a
 * reload. An assistant that forgets the moment you look away is a
 * search box with a slower interface.
 *
 * **On the device, in SQLite, not on the server.** The same idiom the
 * upload outbox already uses (`src/storage/outbox.ts`). A conversation
 * about somebody's own wardrobe is theirs; it does not need to be on a
 * server to be useful, and keeping it local means no migration, no
 * endpoint and nothing new to authorise or to leak. The trade is that
 * it does not follow them to a second device, which is the right trade
 * for a feature whose whole subject is the clothes in one person's
 * room.
 *
 * **Context is the point, not the list.** The history screen is the
 * visible half; the half that matters is that reopening a session
 * restores its turns, so `askStylist` sends the same history it would
 * have sent had the app never been closed.
 */

const MIGRATIONS = [
  `CREATE TABLE IF NOT EXISTS chat_sessions (
     id          TEXT PRIMARY KEY NOT NULL,
     title       TEXT NOT NULL,
     created_at  INTEGER NOT NULL,
     updated_at  INTEGER NOT NULL
   );`,
  `CREATE TABLE IF NOT EXISTS chat_turns (
     id          TEXT PRIMARY KEY NOT NULL,
     session_id  TEXT NOT NULL,
     position    INTEGER NOT NULL,
     who         TEXT NOT NULL,
     text        TEXT NOT NULL,
     shown_with  TEXT,
     payload     TEXT NOT NULL,
     created_at  INTEGER NOT NULL
   );`,
  // Ordering a session's turns is the only read that happens on every
  // open, so it is the one index worth having.
  `CREATE INDEX IF NOT EXISTS chat_turns_by_session
     ON chat_turns (session_id, position);`,
] as const;

/** A conversation, as the history list shows it. */
export interface Session {
  id: string;
  /** Taken from the first thing the person said. */
  title: string;
  createdAt: number;
  updatedAt: number;
}

/**
 * How long a title runs before it is cut.
 *
 * Long enough to tell two conversations apart at a glance, short
 * enough that a row stays one line on the narrowest phone.
 */
const TITLE_LENGTH = 48;

export function titleFrom(text: string): string {
  const cleaned = text.trim().replace(/\s+/g, ' ');
  if (!cleaned) return 'New conversation';
  if (cleaned.length <= TITLE_LENGTH) return cleaned;
  // Cut on a word rather than mid-syllable, when there is one near
  // enough to the limit to be worth it.
  const cut = cleaned.slice(0, TITLE_LENGTH);
  const space = cut.lastIndexOf(' ');
  return `${(space > TITLE_LENGTH - 12 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

export class ChatHistory {
  private constructor(private readonly db: SQLite.SQLiteDatabase) {}

  static async open(databaseName = 'stylist-history.db'): Promise<ChatHistory> {
    const db = await SQLite.openDatabaseAsync(databaseName);
    await db.execAsync('PRAGMA journal_mode = WAL;');
    for (const statement of MIGRATIONS) await db.execAsync(statement);
    return new ChatHistory(db);
  }

  /** Every conversation, most recently used first. */
  async sessions(limit = 60): Promise<Session[]> {
    const rows = await this.db.getAllAsync<{
      id: string;
      title: string;
      created_at: number;
      updated_at: number;
    }>(
      `SELECT id, title, created_at, updated_at FROM chat_sessions
       ORDER BY updated_at DESC LIMIT ?;`,
      [limit],
    );
    return rows.map((row) => ({
      id: row.id,
      title: row.title,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    }));
  }

  /** The turns of one conversation, in the order they were said. */
  async turns(sessionId: string): Promise<Turn[]> {
    const rows = await this.db.getAllAsync<{ payload: string }>(
      `SELECT payload FROM chat_turns WHERE session_id = ?
       ORDER BY position ASC;`,
      [sessionId],
    );
    const out: Turn[] = [];
    for (const row of rows) {
      try {
        out.push(JSON.parse(row.payload) as Turn);
      } catch {
        // One unreadable row must not cost somebody the conversation
        // around it. Skipped rather than thrown: a thread missing a
        // line is recoverable, an empty screen is not.
      }
    }
    return out;
  }

  /**
   * Write the whole conversation under one id.
   *
   * Replace rather than append. A turn is edited in place as it
   * streams - text arrives token by token, a verdict lands, a render
   * id is attached later - so there is no moment at which a turn is
   * final and appendable. Rewriting a thread of a few dozen rows costs
   * nothing and removes every question about which version is current.
   */
  async save(
    sessionId: string,
    turns: readonly Turn[],
    now: number = Date.now(),
  ): Promise<void> {
    if (turns.length === 0) return;
    const title = titleFrom(turns.find((t) => t.who === 'you')?.text ?? '');
    await this.db.withTransactionAsync(async () => {
      await this.db.runAsync(
        `INSERT INTO chat_sessions (id, title, created_at, updated_at)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET title = excluded.title,
                                       updated_at = excluded.updated_at;`,
        [sessionId, title, now, now],
      );
      await this.db.runAsync(`DELETE FROM chat_turns WHERE session_id = ?;`, [
        sessionId,
      ]);
      for (let at = 0; at < turns.length; at += 1) {
        const turn = turns[at];
        await this.db.runAsync(
          `INSERT INTO chat_turns
             (id, session_id, position, who, text, shown_with, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?);`,
          [
            `${sessionId}:${turn.id}`,
            sessionId,
            at,
            turn.who,
            turn.text,
            turn.shownWith ?? null,
            JSON.stringify(turn),
            now,
          ],
        );
      }
    });
  }

  /** Forget one conversation, turns and all. */
  async forget(sessionId: string): Promise<void> {
    await this.db.withTransactionAsync(async () => {
      await this.db.runAsync(`DELETE FROM chat_turns WHERE session_id = ?;`, [
        sessionId,
      ]);
      await this.db.runAsync(`DELETE FROM chat_sessions WHERE id = ?;`, [
        sessionId,
      ]);
    });
  }

  /** Forget everything. Offered in the history screen, confirmed first. */
  async forgetAll(): Promise<void> {
    await this.db.withTransactionAsync(async () => {
      await this.db.runAsync(`DELETE FROM chat_turns;`);
      await this.db.runAsync(`DELETE FROM chat_sessions;`);
    });
  }
}
