/**
 * The question is put once, and skipping counts as answering it.
 *
 * Separate from whether somebody answered, which the server holds. This flag
 * is "has this device shown you the screen", and the distinction is what
 * stops a one-time question becoming a prompt on every launch — the fastest
 * way to make a person dismiss something they might otherwise have filled in.
 *
 * The kv-store is mocked for the reason the welcome tests mock it: the real
 * one opens a SQLite handle that keeps jest alive after the run.
 */

import {
  hasAskedTaste,
  markTasteAsked,
  resetTasteAsked,
} from '@/features/onboarding/taste';

jest.mock('expo-sqlite/kv-store', () => {
  let value: string | null = null;
  let broken = false;
  return {
    __esModule: true,
    default: {
      getItemSync: () => {
        if (broken) throw new Error('storage unavailable');
        return value;
      },
      setItemAsync: async (_key: string, next: string) => {
        value = next;
      },
      __break: (next: boolean) => {
        broken = next;
      },
      __reset: () => {
        value = null;
        broken = false;
      },
    },
  };
});

// eslint-disable-next-line @typescript-eslint/no-require-imports
const store = require('expo-sqlite/kv-store').default;

beforeEach(() => store.__reset());

describe('the taste question', () => {
  it('has not been asked on a fresh device', () => {
    expect(hasAskedTaste()).toBe(false);
  });

  it('stays asked once it has been', async () => {
    await markTasteAsked();
    expect(hasAskedTaste()).toBe(true);
  });

  it('counts skipping as having been asked', async () => {
    // Skipping is an answer. If it did not record, somebody who declined
    // would be asked again every single launch.
    await markTasteAsked();
    expect(hasAskedTaste()).toBe(true);
  });

  it('asks again rather than never, when storage is unreadable', () => {
    store.__break(true);
    // A repeated question beats never personalising at all, so the harmless
    // direction to be wrong in is "ask".
    expect(hasAskedTaste()).toBe(false);
  });

  it('can be re-offered', async () => {
    await markTasteAsked();
    await resetTasteAsked();
    expect(hasAskedTaste()).toBe(false);
  });
});
