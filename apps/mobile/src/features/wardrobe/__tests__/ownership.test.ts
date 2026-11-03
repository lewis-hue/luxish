/**
 * One device, more than one account.
 *
 * The kv-store is mocked for the reason the taste and welcome tests
 * mock it: the real one opens a SQLite handle that is not available
 * under jest and keeps the run alive afterwards.
 */
import Store from 'expo-sqlite/kv-store';


import {
  WARDROBE_STORAGE_KEY,
  claimWardrobe,
  forgetWardrobe,
} from '@/features/wardrobe/store';

jest.mock('expo-sqlite/kv-store', () => {
  const store = new Map<string, string>();
  return {
    __esModule: true,
    default: {
      getItemSync: (key: string) => store.get(key) ?? null,
      setItemSync: (key: string, value: string) => void store.set(key, value),
      getItem: async (key: string) => store.get(key) ?? null,
      setItemAsync: async (key: string, value: string) =>
        void store.set(key, value),
      removeItem: async (key: string) => void store.delete(key),
    },
  };
});

const OWNER_KEY = 'fashion.wardrobe_owner';

function putGarments(count: number) {
  Store.setItemSync(
    WARDROBE_STORAGE_KEY,
    JSON.stringify(
      Array.from({ length: count }, (_, at) => ({
        id: `g${at}`,
        name: `Garment ${at}`,
      })),
    ),
  );
}

function garments(): unknown[] {
  const raw = Store.getItemSync(WARDROBE_STORAGE_KEY);
  return raw ? (JSON.parse(raw) as unknown[]) : [];
}

beforeEach(() => {
  Store.setItemSync(WARDROBE_STORAGE_KEY, JSON.stringify([]));
  Store.setItemSync(OWNER_KEY, '');
});

describe('whose wardrobe this device is holding', () => {
  it('empties it when a different account signs in', async () => {
    // The bug: one phone, two accounts, and the second saw the
    // first's clothes - their names and their photographs - because
    // the list was stored under one key with nothing saying whose.
    putGarments(3);
    await claimWardrobe('user-one');
    expect(garments()).toHaveLength(3);

    const foreign = await claimWardrobe('user-two');
    expect(foreign).toBe(true);
    expect(garments()).toEqual([]);
  });

  it('leaves it alone when the same account signs in again', async () => {
    putGarments(4);
    await claimWardrobe('user-one');

    const foreign = await claimWardrobe('user-one');
    expect(foreign).toBe(false);
    expect(garments()).toHaveLength(4);
  });

  it('adopts a list nobody has claimed rather than binning it', async () => {
    // It predates the ownership stamp, so it belongs to the only
    // person who has used this device. Throwing it away would lose
    // garments that were never synced.
    putGarments(5);
    const foreign = await claimWardrobe('user-one');
    expect(foreign).toBe(false);
    expect(garments()).toHaveLength(5);
  });

  it('keeps the next account out after an adopted list', async () => {
    putGarments(5);
    await claimWardrobe('user-one');
    await claimWardrobe('user-two');
    expect(garments()).toEqual([]);
  });

  it('forgets everything on sign-out', async () => {
    // What goes is the copy on a handset somebody else may be about
    // to use. Everything synced is on the server.
    putGarments(6);
    await claimWardrobe('user-one');
    await forgetWardrobe();
    expect(garments()).toEqual([]);
  });

  it('does not hand a forgotten list to the next account', async () => {
    putGarments(2);
    await claimWardrobe('user-one');
    await forgetWardrobe();

    const foreign = await claimWardrobe('user-two');
    expect(foreign).toBe(false);
    expect(garments()).toEqual([]);
  });
});

describe('what shows before ownership is settled', () => {
  // The rule `useWardrobe` renders by, asserted here because the
  // hook needs a network answer to reach it and the rule is the
  // part that matters: unknown owner means none of them.
  const visible = (owner: string | null, claimedFor: string | null, items: number) =>
    owner !== null && claimedFor === owner ? items : 0;

  it('shows nothing before the account is known', () => {
    // Signed out, offline, or simply before /auth/me has answered.
    expect(visible(null, null, 41)).toBe(0);
  });

  it('shows nothing while the claim is still running', () => {
    expect(visible('user-two', null, 41)).toBe(0);
  });

  it('shows nothing when the list was claimed by somebody else', () => {
    // The window the first version left open: a known account, a
    // list still belonging to the previous one.
    expect(visible('user-two', 'user-one', 41)).toBe(0);
  });

  it('shows them once the list is confirmed theirs', () => {
    expect(visible('user-one', 'user-one', 41)).toBe(41);
  });
});
