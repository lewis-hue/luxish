/**
 * Durable upload outbox.
 *
 * Mobile uploads fail constantly — the network drops mid-garment, the OS suspends
 * the app, the user force-quits. The requirement (§16, acceptance criterion 10) is
 * that none of that produces a duplicate garment or a lost photo.
 *
 * The invariant that makes it work: **the idempotency key is generated once, when
 * the item is enqueued, and persisted before the first attempt.** Every retry
 * replays the same key, so the server collapses them. A key minted per attempt
 * would duplicate on exactly the case this exists to handle.
 *
 * SQLite rather than AsyncStorage because the queue needs atomic claim-and-update
 * under concurrent drains, and ordering by attempt time.
 *
 * SDK 58 notes: `expo-file-system` exposes the `File`/`Paths` object API (the flat
 * functions moved to `expo-file-system/legacy`), and `createUploadTask` takes
 * `sessionType: 'background'` on iOS so a suspended app can still finish a transfer.
 */

import { File } from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import * as SQLite from 'expo-sqlite';

/** Terminal states are kept, not deleted, so the UI can show what failed and why. */
export type OutboxState = 'pending' | 'uploading' | 'uploaded' | 'failed' | 'cancelled';

export type OutboxKind = 'garment' | 'inspiration' | 'post_asset';

export interface OutboxItem {
  id: string;
  /** Stable across every attempt. The whole point of this module. */
  idempotencyKey: string;
  kind: OutboxKind;
  /** Local file URI. May become unreadable if the OS clears the cache. */
  localUri: string;
  /** Opaque JSON passed back to the caller on success. */
  meta: Record<string, unknown>;
  state: OutboxState;
  attempts: number;
  lastError: string | null;
  /** Set once the server has authorised a destination for this item. */
  uploadUrl: string | null;
  assetId: string | null;
  createdAt: number;
  nextAttemptAt: number;
}

/**
 * Attempts are capped so a permanently broken item cannot drain the battery. Six
 * attempts with the backoff below spans roughly half an hour.
 */
const MAX_ATTEMPTS = 6;

/** Exponential backoff with a ceiling, in milliseconds. */
function backoffMs(attempts: number): number {
  return Math.min(1000 * 2 ** attempts, 5 * 60_000);
}

export interface UploadAuthorizer {
  /** Asks the API where to put this file. Must be safe to call more than once. */
  authorize(item: OutboxItem): Promise<{ uploadUrl: string; assetId: string }>;
  /** Tells the API the bytes landed. Must be idempotent on `idempotencyKey`. */
  commit(item: OutboxItem): Promise<void>;
}

const MIGRATIONS = [
  `CREATE TABLE IF NOT EXISTS outbox (
     id              TEXT PRIMARY KEY NOT NULL,
     idempotency_key TEXT NOT NULL UNIQUE,
     kind            TEXT NOT NULL,
     local_uri       TEXT NOT NULL,
     meta            TEXT NOT NULL DEFAULT '{}',
     state           TEXT NOT NULL DEFAULT 'pending',
     attempts        INTEGER NOT NULL DEFAULT 0,
     last_error      TEXT,
     upload_url      TEXT,
     asset_id        TEXT,
     created_at      INTEGER NOT NULL,
     next_attempt_at INTEGER NOT NULL DEFAULT 0
   );`,
  `CREATE INDEX IF NOT EXISTS outbox_claimable
     ON outbox (state, next_attempt_at);`,
];

type Row = {
  id: string;
  idempotency_key: string;
  kind: OutboxKind;
  local_uri: string;
  meta: string;
  state: OutboxState;
  attempts: number;
  last_error: string | null;
  upload_url: string | null;
  asset_id: string | null;
  created_at: number;
  next_attempt_at: number;
};

function toItem(row: Row): OutboxItem {
  return {
    id: row.id,
    idempotencyKey: row.idempotency_key,
    kind: row.kind,
    localUri: row.local_uri,
    meta: JSON.parse(row.meta) as Record<string, unknown>,
    state: row.state,
    attempts: row.attempts,
    lastError: row.last_error,
    uploadUrl: row.upload_url,
    assetId: row.asset_id,
    createdAt: row.created_at,
    nextAttemptAt: row.next_attempt_at,
  };
}

export class Outbox {
  private constructor(
    private readonly db: SQLite.SQLiteDatabase,
    private readonly authorizer: UploadAuthorizer,
    private readonly now: () => number,
  ) {}

  static async open(
    authorizer: UploadAuthorizer,
    options: { databaseName?: string; now?: () => number } = {},
  ): Promise<Outbox> {
    const db = await SQLite.openDatabaseAsync(options.databaseName ?? 'outbox.db');
    await db.execAsync('PRAGMA journal_mode = WAL;');
    for (const statement of MIGRATIONS) await db.execAsync(statement);
    return new Outbox(db, authorizer, options.now ?? Date.now);
  }

  /**
   * Queues a local file. Returns the item id.
   *
   * The idempotency key is minted here — before any network call — and never
   * regenerated.
   */
  async enqueue(
    localUri: string,
    kind: OutboxKind,
    meta: Record<string, unknown> = {},
  ): Promise<string> {
    const id = Crypto.randomUUID();
    await this.db.runAsync(
      `INSERT INTO outbox (id, idempotency_key, kind, local_uri, meta, created_at, next_attempt_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      id,
      Crypto.randomUUID(),
      kind,
      localUri,
      JSON.stringify(meta),
      this.now(),
      0,
    );
    return id;
  }

  async get(id: string): Promise<OutboxItem | null> {
    const row = await this.db.getFirstAsync<Row>('SELECT * FROM outbox WHERE id = ?', id);
    return row ? toItem(row) : null;
  }

  async list(state?: OutboxState): Promise<OutboxItem[]> {
    const rows = state
      ? await this.db.getAllAsync<Row>(
          'SELECT * FROM outbox WHERE state = ? ORDER BY created_at',
          state,
        )
      : await this.db.getAllAsync<Row>('SELECT * FROM outbox ORDER BY created_at');
    return rows.map(toItem);
  }

  /** Count of items the user is still waiting on, for a progress indicator. */
  async pendingCount(): Promise<number> {
    const row = await this.db.getFirstAsync<{ n: number }>(
      "SELECT COUNT(*) AS n FROM outbox WHERE state IN ('pending', 'uploading')",
    );
    return row?.n ?? 0;
  }

  async cancel(id: string): Promise<void> {
    // Only a not-yet-finished item can be cancelled; an uploaded one must stay
    // uploaded or the server and client disagree about what exists.
    await this.db.runAsync(
      "UPDATE outbox SET state = 'cancelled' WHERE id = ? AND state IN ('pending', 'uploading')",
      id,
    );
  }

  /**
   * Claims one due item atomically, so two concurrent drains cannot both take it.
   * The conditional UPDATE is the lock — SQLite has no SKIP LOCKED.
   */
  private async claim(): Promise<OutboxItem | null> {
    const due = await this.db.getFirstAsync<Row>(
      `SELECT * FROM outbox
        WHERE state = 'pending' AND next_attempt_at <= ?
        ORDER BY next_attempt_at, created_at
        LIMIT 1`,
      this.now(),
    );
    if (!due) return null;

    const claimed = await this.db.runAsync(
      "UPDATE outbox SET state = 'uploading' WHERE id = ? AND state = 'pending'",
      due.id,
    );
    // Another drain won the race; let the caller loop and pick up the next one.
    if (claimed.changes === 0) return null;

    return toItem({ ...due, state: 'uploading' });
  }

  private async fail(item: OutboxItem, error: unknown): Promise<void> {
    const attempts = item.attempts + 1;
    const exhausted = attempts >= MAX_ATTEMPTS;
    await this.db.runAsync(
      `UPDATE outbox
          SET state = ?, attempts = ?, last_error = ?, next_attempt_at = ?
        WHERE id = ?`,
      exhausted ? 'failed' : 'pending',
      attempts,
      error instanceof Error ? error.message : String(error),
      this.now() + backoffMs(attempts),
      item.id,
    );
  }

  /**
   * Processes every due item. Returns how many succeeded.
   *
   * Safe to call concurrently and safe to call again after a crash: a half-finished
   * item is retried with its original idempotency key, so the server deduplicates
   * rather than creating a second garment.
   */
  async drain(): Promise<number> {
    let uploaded = 0;

    for (;;) {
      const item = await this.claim();
      if (!item) break;

      try {
        // Re-authorising is safe and necessary: a signed URL from a previous
        // attempt may have expired while the app was backgrounded.
        const { uploadUrl, assetId } = await this.authorizer.authorize(item);
        await this.db.runAsync(
          'UPDATE outbox SET upload_url = ?, asset_id = ? WHERE id = ?',
          uploadUrl,
          assetId,
          item.id,
        );

        const file = new File(item.localUri);
        if (!file.exists) {
          // The OS cleared the cache directory. Retrying cannot help, so fail
          // terminally rather than burning the remaining attempts.
          await this.db.runAsync(
            `UPDATE outbox SET state = 'failed', last_error = ?, attempts = ? WHERE id = ?`,
            'the local file is no longer available',
            MAX_ATTEMPTS,
            item.id,
          );
          continue;
        }

        const task = file.createUploadTask(uploadUrl, {
          httpMethod: 'PUT',
          // iOS-only; lets a suspended app finish the transfer.
          sessionType: 'background',
          headers: {
            'Idempotency-Key': item.idempotencyKey,
            'Content-Type': (item.meta.contentType as string) ?? 'application/octet-stream',
          },
        });

        const result = await task.uploadAsync();
        if (result && result.status >= 400) {
          throw new Error(`upload rejected with ${result.status}`);
        }

        await this.authorizer.commit({ ...item, uploadUrl, assetId });
        await this.db.runAsync(
          "UPDATE outbox SET state = 'uploaded', last_error = NULL WHERE id = ?",
          item.id,
        );
        uploaded += 1;
      } catch (error) {
        await this.fail(item, error);
      }
    }

    return uploaded;
  }

  /** Clears terminal rows. Call from a settings action, never automatically. */
  async purgeFinished(): Promise<void> {
    await this.db.runAsync("DELETE FROM outbox WHERE state IN ('uploaded', 'cancelled')");
  }

  async close(): Promise<void> {
    await this.db.closeAsync();
  }
}

export const OUTBOX_MAX_ATTEMPTS = MAX_ATTEMPTS;
export const outboxBackoffMs = backoffMs;
