/**
 * Conversations survive the screen.
 *
 * The thread used to live in a `useState` and die with the tab, so
 * leaving the wardrobe threw away everything that had been said. The
 * properties worth pinning are the ones that make it an assistant
 * rather than a search box: a reopened conversation comes back whole
 * and in order, a thread rewritten mid-stream does not duplicate, and
 * forgetting one really forgets it.
 */

jest.mock('expo-sqlite', () => {
  // `require` inside the factory, because a top-level import would be an
  // out-of-scope reference for babel-plugin-jest-hoist.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { DatabaseSync } = require('node:sqlite') as typeof import('node:sqlite');
  const handles = new Map<string, InstanceType<typeof DatabaseSync>>();
  const flat = (params: unknown[]): unknown[] =>
    params.length === 1 && Array.isArray(params[0])
      ? (params[0] as unknown[])
      : params;
  return {
    openDatabaseAsync: async (name: string) => {
      // ':memory:' is per-connection, so one name must map to one handle,
      // or reopening would lose rows a real device would keep.
      let handle = handles.get(name);
      if (!handle) {
        handle = new DatabaseSync(':memory:');
        handles.set(name, handle);
      }
      return {
        execAsync: async (sql: string) => {
          handle.exec(sql);
        },
        // expo-sqlite takes either varargs or a single array; this
        // module passes an array, so the mock has to accept both or
        // node:sqlite reads the array itself as a named parameter.
        runAsync: async (sql: string, ...params: unknown[]) => {
          const result = handle.prepare(sql).run(...(flat(params) as never[]));
          return { changes: Number(result.changes), lastInsertRowId: 0 };
        },
        getFirstAsync: async (sql: string, ...params: unknown[]) =>
          handle.prepare(sql).get(...(flat(params) as never[])) ?? null,
        getAllAsync: async (sql: string, ...params: unknown[]) =>
          handle.prepare(sql).all(...(flat(params) as never[])),
        withTransactionAsync: async (body: () => Promise<void>) => {
          await body();
        },
        closeAsync: async () => {},
      };
    },
  };
});

// Imported below the mock deliberately: the module under test must resolve
// the mocked native module, so this cannot move to the top of the file.
/* eslint-disable import/first */
import type { Turn } from '@/features/stylist/conversation';
import { ChatHistory, titleFrom } from '@/features/stylist/history';
/* eslint-enable import/first */

let counter = 0;
const freshDb = () => `history-test-${(counter += 1)}.db`;

function said(text: string): Turn {
  return { id: `t${text.length}${text.slice(0, 3)}`, who: 'you', text };
}
function replied(text: string, extra: Partial<Turn> = {}): Turn {
  return { id: `r${text.length}${text.slice(0, 3)}`, who: 'stylist', text, ...extra };
}

describe('keeping a conversation', () => {
  it('gives back exactly what was put in, in order', async () => {
    const db = await ChatHistory.open(freshDb());
    const turns = [said('what goes with the camel coat'), replied('The cream knit.')];

    await db.save('s1', turns);

    expect(await db.turns('s1')).toEqual(turns);
  });

  it('keeps the parts of a turn that are not its text', async () => {
    // A turn carries a verdict, a render id and the picture it was
    // asked about. Restoring only the words would lose the answer.
    const db = await ChatHistory.open(freshDb());
    const turn = replied('Yes, you have this.', {
      renderId: 'render-9',
      verdict: { answer: 'Yes.', hasMatch: true, using: [], missing: [] },
    } as Partial<Turn>);

    await db.save('s1', [said('do I own this'), turn]);

    const [, back] = await db.turns('s1');
    expect(back.renderId).toBe('render-9');
    expect(back.verdict?.hasMatch).toBe(true);
  });

  it('carries the picture the question was asked about', async () => {
    const db = await ChatHistory.open(freshDb());
    const asked: Turn = { ...said('style this'), shownWith: 'file:///pin.jpg' };

    await db.save('s1', [asked]);

    expect((await db.turns('s1'))[0].shownWith).toBe('file:///pin.jpg');
  });

  it('replaces the thread rather than appending to it', async () => {
    // **The property the whole write path depends on.** A turn is
    // edited in place as it streams, so the same session is saved
    // many times with a growing thread. Appending would leave one
    // conversation holding every intermediate version of itself.
    const db = await ChatHistory.open(freshDb());

    await db.save('s1', [said('hello')]);
    await db.save('s1', [said('hello'), replied('Hi.')]);
    await db.save('s1', [said('hello'), replied('Hi there.')]);

    const turns = await db.turns('s1');
    expect(turns).toHaveLength(2);
    expect(turns[1].text).toBe('Hi there.');
  });

  it('lists conversations most recently used first', async () => {
    const db = await ChatHistory.open(freshDb());
    await db.save('older', [said('about the boots')], 1_000);
    await db.save('newer', [said('about the coat')], 2_000);

    expect((await db.sessions()).map((s) => s.id)).toEqual(['newer', 'older']);
  });

  it('titles a conversation from the first thing the person said', async () => {
    const db = await ChatHistory.open(freshDb());
    await db.save('s1', [
      replied('Opening line from the stylist.'),
      said('what goes with the camel coat'),
    ]);

    expect((await db.sessions())[0].title).toBe('what goes with the camel coat');
  });

  it('forgets one conversation and leaves the rest', async () => {
    const db = await ChatHistory.open(freshDb());
    await db.save('keep', [said('keep me')]);
    await db.save('drop', [said('drop me')]);

    await db.forget('drop');

    expect((await db.sessions()).map((s) => s.id)).toEqual(['keep']);
    expect(await db.turns('drop')).toEqual([]);
  });

  it('forgets everything when asked', async () => {
    const db = await ChatHistory.open(freshDb());
    await db.save('a', [said('one')]);
    await db.save('b', [said('two')]);

    await db.forgetAll();

    expect(await db.sessions()).toEqual([]);
  });

  it('writes nothing for an empty thread', async () => {
    // Opening the tab and leaving must not litter the list with
    // blank conversations.
    const db = await ChatHistory.open(freshDb());
    await db.save('s1', []);
    expect(await db.sessions()).toEqual([]);
  });

  it('survives being reopened', async () => {
    const name = freshDb();
    const first = await ChatHistory.open(name);
    await first.save('s1', [said('remember this')]);

    const again = await ChatHistory.open(name);
    expect((await again.turns('s1'))[0].text).toBe('remember this');
  });
});

describe('titles', () => {
  it('uses the sentence when it is short enough', () => {
    expect(titleFrom('what shoes go with this')).toBe('what shoes go with this');
  });

  it('cuts a long one on a word rather than mid-syllable', () => {
    const title = titleFrom(
      'what shoes would go with the camel coat and the cream knit I bought',
    );
    expect(title.endsWith('…')).toBe(true);
    expect(title.length).toBeLessThanOrEqual(49);
    expect(title).not.toMatch(/\s…$/);
  });

  it('names an empty thread rather than showing a blank row', () => {
    expect(titleFrom('   ')).toBe('New conversation');
  });
});
