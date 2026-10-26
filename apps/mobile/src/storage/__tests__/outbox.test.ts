/**
 * Acceptance criterion 10: "Interrupted uploads and repeated requests do not
 * duplicate items, posts, or charges."
 *
 * `expo-sqlite` is mocked over Node's built-in `node:sqlite` rather than a
 * hand-written fake, so the conditional-UPDATE claim is exercised against real SQL
 * semantics — a fake would happily let both drains win the race the claim exists to
 * prevent.
 */

// --- mocks -------------------------------------------------------------------

// babel-plugin-jest-hoist lifts these factories above every declaration, and only
// allows them to close over identifiers prefixed `mock`. Anything the factory body
// touches at definition time must also live inside the factory — hence the handle
// map below is declared in place rather than at module scope.
let mockUuidCounter = 0;
jest.mock('expo-crypto', () => ({
  randomUUID: () => `uuid-${++mockUuidCounter}`,
}));

const mockFileState = new Map<string, { exists: boolean }>();
type UploadAttempt = { url: string; headers: Record<string, string> };
const mockUploadAttempts: UploadAttempt[] = [];
const mockUpload: { behaviour: () => { status: number } } = {
  behaviour: () => ({ status: 200 }),
};

jest.mock('expo-file-system', () => ({
  File: class {
    // A plain field, not a TS parameter property: the latter desugars into
    // something babel-plugin-jest-hoist reads as an out-of-scope `uri` reference.
    uri: string;
    constructor(uri: string) {
      this.uri = uri;
    }
    get exists() {
      return mockFileState.get(this.uri)?.exists ?? true;
    }
    createUploadTask(url: string, options: { headers: Record<string, string> }) {
      return {
        uploadAsync: async () => {
          mockUploadAttempts.push({ url, headers: options.headers });
          return mockUpload.behaviour();
        },
      };
    }
  },
}));

jest.mock('expo-sqlite', () => {
  // `require` inside the factory, because a top-level import would be an
  // out-of-scope reference for babel-plugin-jest-hoist.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { DatabaseSync } = require('node:sqlite') as typeof import('node:sqlite');
  const handles = new Map<string, InstanceType<typeof DatabaseSync>>();
  return {
    openDatabaseAsync: async (name: string) => {
      // ':memory:' is per-connection, so a given name must map to one handle —
      // otherwise reopening the outbox would lose rows a real device would keep.
      let handle = handles.get(name);
      if (!handle) {
        handle = new DatabaseSync(':memory:');
        handles.set(name, handle);
      }
      return {
        execAsync: async (sql: string) => {
          handle.exec(sql);
        },
        runAsync: async (sql: string, ...params: unknown[]) => {
          const result = handle.prepare(sql).run(...(params as never[]));
          return { changes: Number(result.changes), lastInsertRowId: 0 };
        },
        getFirstAsync: async (sql: string, ...params: unknown[]) =>
          handle.prepare(sql).get(...(params as never[])) ?? null,
        getAllAsync: async (sql: string, ...params: unknown[]) =>
          handle.prepare(sql).all(...(params as never[])),
        closeAsync: async () => {},
      };
    },
  };
});

// Imported below the mocks deliberately: the module under test must resolve the
// mocked native modules, so these cannot move to the top of the file.
/* eslint-disable import/first */
import { Outbox, OUTBOX_MAX_ATTEMPTS, outboxBackoffMs } from '@/storage/outbox';
import type { OutboxItem, UploadAuthorizer } from '@/storage/outbox';
/* eslint-enable import/first */

// --- harness -----------------------------------------------------------------

let dbCounter = 0;
let clock = 1_000_000;

function authorizerSpy(overrides: Partial<UploadAuthorizer> = {}) {
  const committed: OutboxItem[] = [];
  const authorized: OutboxItem[] = [];
  const authorizer: UploadAuthorizer = {
    authorize: async (item) => {
      authorized.push(item);
      return { uploadUrl: `https://storage.test/put/${item.id}`, assetId: `asset-${item.id}` };
    },
    commit: async (item) => {
      committed.push(item);
    },
    ...overrides,
  };
  return { authorizer, committed, authorized };
}

async function openOutbox(authorizer: UploadAuthorizer) {
  return Outbox.open(authorizer, {
    databaseName: `test-${++dbCounter}.db`,
    now: () => clock,
  });
}

beforeEach(() => {
  mockUuidCounter = 0;
  clock = 1_000_000;
  mockUploadAttempts.length = 0;
  mockFileState.clear();
  mockUpload.behaviour = () => ({ status: 200 });
});

// --- the load-bearing test ---------------------------------------------------

describe('idempotency', () => {
  it('an interrupted upload retried twice replays one idempotency key', async () => {
    const { authorizer, committed } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    await outbox.enqueue('file:///garment.jpg', 'garment');

    // First drain fails mid-upload, as a dropped connection would.
    mockUpload.behaviour = () => {
      throw new Error('socket hung up');
    };
    expect(await outbox.drain()).toBe(0);

    // Backoff has to elapse before the item is due again.
    clock += outboxBackoffMs(1) + 1;
    mockUpload.behaviour = () => ({ status: 200 });
    expect(await outbox.drain()).toBe(1);

    // Two transport attempts, one key — so the server sees one garment.
    expect(mockUploadAttempts).toHaveLength(2);
    const keys = new Set(mockUploadAttempts.map((a) => a.headers['Idempotency-Key']));
    expect(keys.size).toBe(1);
    expect(committed).toHaveLength(1);
  });

  it('gives every enqueued item its own key', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    await outbox.enqueue('file:///a.jpg', 'garment');
    await outbox.enqueue('file:///b.jpg', 'garment');

    await outbox.drain();
    const keys = mockUploadAttempts.map((a) => a.headers['Idempotency-Key']);
    expect(new Set(keys).size).toBe(2);
  });

  it('persists the key before the first attempt, not per attempt', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const id = await outbox.enqueue('file:///c.jpg', 'garment');

    // Readable before any network call has happened.
    const beforeAnyAttempt = await outbox.get(id);
    expect(beforeAnyAttempt?.idempotencyKey).toBeTruthy();

    await outbox.drain();
    expect(mockUploadAttempts[0].headers['Idempotency-Key']).toBe(
      beforeAnyAttempt?.idempotencyKey,
    );
  });
});

// --- concurrency -------------------------------------------------------------

describe('claiming', () => {
  it('two concurrent drains never upload the same item twice', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    for (let i = 0; i < 5; i += 1) {
      await outbox.enqueue(`file:///item-${i}.jpg`, 'garment');
    }

    const [a, b] = await Promise.all([outbox.drain(), outbox.drain()]);

    expect(a + b).toBe(5);
    expect(mockUploadAttempts).toHaveLength(5);
    const urls = mockUploadAttempts.map((attempt) => attempt.url);
    expect(new Set(urls).size).toBe(5);
  });
});

// --- failure handling --------------------------------------------------------

describe('failure handling', () => {
  it('stops retrying after the attempt cap and records why', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const id = await outbox.enqueue('file:///doomed.jpg', 'garment');
    mockUpload.behaviour = () => {
      throw new Error('always broken');
    };

    for (let attempt = 0; attempt < OUTBOX_MAX_ATTEMPTS + 2; attempt += 1) {
      await outbox.drain();
      clock += outboxBackoffMs(attempt + 1) + 1;
    }

    const item = await outbox.get(id);
    expect(item?.state).toBe('failed');
    expect(item?.attempts).toBe(OUTBOX_MAX_ATTEMPTS);
    expect(item?.lastError).toContain('always broken');
    // Capped, not unbounded — a broken item must not drain the battery.
    expect(mockUploadAttempts).toHaveLength(OUTBOX_MAX_ATTEMPTS);
  });

  it('fails terminally when the OS has cleared the local file', async () => {
    const { authorizer, committed } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const id = await outbox.enqueue('file:///evicted.jpg', 'garment');
    mockFileState.set('file:///evicted.jpg', { exists: false });

    await outbox.drain();

    const item = await outbox.get(id);
    // Retrying cannot conjure the bytes back, so it must not burn six attempts.
    expect(item?.state).toBe('failed');
    expect(item?.lastError).toContain('no longer available');
    expect(mockUploadAttempts).toHaveLength(0);
    expect(committed).toHaveLength(0);
  });

  it('treats an HTTP error status as a failure, not a success', async () => {
    const { authorizer, committed } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const id = await outbox.enqueue('file:///rejected.jpg', 'garment');
    mockUpload.behaviour = () => ({ status: 403 });

    expect(await outbox.drain()).toBe(0);
    expect((await outbox.get(id))?.state).toBe('pending');
    expect(committed).toHaveLength(0);
  });

  it('does not commit when the upload itself failed', async () => {
    const { authorizer, committed } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    await outbox.enqueue('file:///x.jpg', 'garment');
    mockUpload.behaviour = () => {
      throw new Error('nope');
    };

    await outbox.drain();
    expect(committed).toHaveLength(0);
  });

  it('re-authorises on each attempt so an expired signed URL recovers', async () => {
    const { authorizer, authorized } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    await outbox.enqueue('file:///y.jpg', 'garment');

    mockUpload.behaviour = () => ({ status: 403 });
    await outbox.drain();
    clock += outboxBackoffMs(1) + 1;
    mockUpload.behaviour = () => ({ status: 200 });
    await outbox.drain();

    expect(authorized).toHaveLength(2);
  });
});

// --- queue behaviour ---------------------------------------------------------

describe('queue', () => {
  it('backs off exponentially with a ceiling', () => {
    expect(outboxBackoffMs(1)).toBeLessThan(outboxBackoffMs(3));
    expect(outboxBackoffMs(99)).toBe(5 * 60_000);
  });

  it('does not retry before the backoff has elapsed', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    await outbox.enqueue('file:///z.jpg', 'garment');
    mockUpload.behaviour = () => {
      throw new Error('fail once');
    };

    await outbox.drain();
    expect(mockUploadAttempts).toHaveLength(1);

    // Same clock: nothing is due, so no second attempt.
    await outbox.drain();
    expect(mockUploadAttempts).toHaveLength(1);
  });

  it('reports how many items the user is still waiting on', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    await outbox.enqueue('file:///p.jpg', 'garment');
    await outbox.enqueue('file:///q.jpg', 'garment');
    expect(await outbox.pendingCount()).toBe(2);

    await outbox.drain();
    expect(await outbox.pendingCount()).toBe(0);
  });

  it('cancels a pending item but never an uploaded one', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const pending = await outbox.enqueue('file:///r.jpg', 'garment');
    await outbox.cancel(pending);
    expect((await outbox.get(pending))?.state).toBe('cancelled');

    const done = await outbox.enqueue('file:///s.jpg', 'garment');
    await outbox.drain();
    await outbox.cancel(done);
    // Cancelling an uploaded item would make client and server disagree.
    expect((await outbox.get(done))?.state).toBe('uploaded');
  });

  it('skips cancelled items when draining', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const id = await outbox.enqueue('file:///t.jpg', 'garment');
    await outbox.cancel(id);

    expect(await outbox.drain()).toBe(0);
    expect(mockUploadAttempts).toHaveLength(0);
  });

  it('keeps failed rows after purging finished ones, so the user can see them', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const ok = await outbox.enqueue('file:///ok.jpg', 'garment');
    await outbox.drain();

    const bad = await outbox.enqueue('file:///bad.jpg', 'garment');
    mockFileState.set('file:///bad.jpg', { exists: false });
    await outbox.drain();

    await outbox.purgeFinished();
    expect(await outbox.get(ok)).toBeNull();
    expect((await outbox.get(bad))?.state).toBe('failed');
  });

  it('round-trips caller metadata', async () => {
    const { authorizer } = authorizerSpy();
    const outbox = await openOutbox(authorizer);
    const id = await outbox.enqueue('file:///m.jpg', 'inspiration', {
      contentType: 'image/jpeg',
      sourceUrl: 'https://example.test/post',
    });

    expect((await outbox.get(id))?.meta).toEqual({
      contentType: 'image/jpeg',
      sourceUrl: 'https://example.test/post',
    });
    await outbox.drain();
    expect(mockUploadAttempts[0].headers['Content-Type']).toBe('image/jpeg');
  });
});
