/**
 * Ranking by interaction.
 *
 * The behaviour worth pinning is the decay and the weighting — a score with no
 * decay makes a look you opened once in January outrank what you are into now,
 * which is the opposite of what the feature is for.
 *
 * `rank` is pure, but importing the module pulls in the kv-store, which opens a
 * SQLite handle that keeps jest alive after the run. Mocked here so these stay
 * fast and the process exits.
 */

import {
  INTERACTION_WINDOW_DAYS,
  rank,
  type InteractionEvent,
} from '@/features/discover/interactions';

jest.mock('expo-sqlite/kv-store', () => ({
  __esModule: true,
  default: {
    getItemSync: () => null,
    setItemAsync: async () => undefined,
  },
}));

const NOW = 1_800_000_000_000;
const DAY = 24 * 60 * 60 * 1000;

function event(
  lookId: string,
  kind: InteractionEvent['kind'],
  daysAgo = 0,
): InteractionEvent {
  return { lookId, kind, at: NOW - daysAgo * DAY, aesthetics: [] };
}

describe('ranking', () => {
  it('weights intent above attention', () => {
    // Saving says "I expect to come back"; a view includes curiosity and mistakes.
    const ranked = rank([event('a', 'view'), event('b', 'save')], NOW);
    expect(ranked[0].lookId).toBe('b');
  });

  it('orders the signal kinds by how much intent they demonstrate', () => {
    const ranked = rank(
      [
        event('viewed', 'view'),
        event('searched', 'search_piece'),
        event('asked', 'ask_stylist'),
        event('saved', 'save'),
      ],
      NOW,
    );
    expect(ranked.map((entry) => entry.lookId)).toEqual([
      'saved',
      'asked',
      'searched',
      'viewed',
    ]);
  });

  it('decays old events so recent interest wins', () => {
    // One fresh view should beat one view from nearly a month ago.
    const ranked = rank(
      [event('stale', 'view', INTERACTION_WINDOW_DAYS - 1), event('fresh', 'view', 0)],
      NOW,
    );
    expect(ranked[0].lookId).toBe('fresh');
  });

  it('ignores events outside the window entirely', () => {
    const ranked = rank([event('ancient', 'save', INTERACTION_WINDOW_DAYS + 1)], NOW);
    expect(ranked).toEqual([]);
  });

  it('accumulates repeated interest on one look', () => {
    const ranked = rank(
      [event('a', 'view'), event('a', 'view'), event('a', 'view'), event('b', 'view')],
      NOW,
    );
    expect(ranked[0].lookId).toBe('a');
    expect(ranked[0].score).toBeGreaterThan(ranked[1].score);
  });

  it('reports which signals produced a ranking, without duplicates', () => {
    const ranked = rank(
      [event('a', 'view'), event('a', 'view'), event('a', 'save')],
      NOW,
    );
    expect(new Set(ranked[0].signals)).toEqual(new Set(['view', 'save']));
  });

  it('returns nothing rather than inventing a ranking from no data', () => {
    // A trending list with no interactions behind it is a fabrication.
    expect(rank([], NOW)).toEqual([]);
  });
});
