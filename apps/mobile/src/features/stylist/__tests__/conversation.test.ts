/**
 * The stylist conversation as a thread rather than a result slot.
 *
 * The panel used to hold one outcome: you asked, it answered, and
 * asking again discarded the answer. That made the obvious
 * follow-ups impossible - "what about with the boots instead", "show
 * me that on me" - because the thing being referred to was no longer
 * on screen.
 */

import {
  asked,
  begin,
  busy,
  canTryOn,
  decided,
  drawing,
  failed,
  history,
  settled,
  shopped,
  streamed,
  type Turn,
} from '@/features/stylist/conversation';

const VERDICT = { hasMatch: true, using: ['g1'], missing: [] };

function reply(text: string) {
  let state = asked(begin(), 'what goes with this?');
  for (const chunk of text.split(' ')) state = streamed(state, `${chunk} `);
  return settled(state);
}

describe('a turn at a time', () => {
  it('keeps the question and makes room for the answer', () => {
    const state = asked(begin(), 'what goes with this?');
    expect(state.turns.map((t) => t.who)).toEqual(['you', 'stylist']);
    expect(state.turns[0].text).toBe('what goes with this?');
    expect(state.turns[1].streaming).toBe(true);
  });

  it('ignores an empty question', () => {
    expect(asked(begin(), '   ').turns).toHaveLength(0);
  });

  it('appends streamed words rather than replacing them', () => {
    let state = asked(begin(), 'q');
    state = streamed(state, 'Yes, ');
    state = streamed(state, 'you do.');
    expect(state.turns[1].text).toBe('Yes, you do.');
  });

  it('**keeps earlier turns when a second question is asked**', () => {
    // The whole reason this exists.
    let state = reply('first answer');
    state = asked(state, 'and with boots?');
    expect(state.turns).toHaveLength(4);
    expect(state.turns[1].text.trim()).toBe('first answer');
  });

  it('gives every turn a distinct key', () => {
    let state = reply('one');
    state = asked(state, 'two');
    const ids = state.turns.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('what a reply carries', () => {
  it('records the verdict and the shopping on the right turn', () => {
    let state = asked(begin(), 'q');
    state = streamed(state, 'No.');
    state = decided(state, { hasMatch: false, using: [], missing: ['boots'] });
    state = shopped(state, [
      {
        product_id: 'p',
        title: 'Boots',
        retailer: null,
        url: null,
        match_label: null,
      },
    ]);
    expect(state.turns[1].verdict?.missing).toEqual(['boots']);
    expect(state.turns[1].shopping).toHaveLength(1);
  });

  it('never leaves a blank bubble', () => {
    const state = settled(asked(begin(), 'q'));
    expect(state.turns[1].text).toBeTruthy();
  });

  it('says something sensible for a picture-only reply', () => {
    let state = asked(begin(), 'show me that on me');
    state = drawing(state, 'r1');
    state = settled(state);
    expect(state.turns[1].text).toBe('Here it is.');
  });

  it('marks a failure without losing what was already said', () => {
    let state = asked(begin(), 'q');
    state = streamed(state, 'Half a sen');
    state = failed(state);
    expect(state.turns[1].failed).toBe(true);
    expect(state.turns[1].text).toBe('Half a sen');
  });
});

describe('what goes back to the model', () => {
  it('sends settled turns oldest first', () => {
    let state = reply('first');
    state = asked(state, 'second');
    state = settled(streamed(state, 'reply two'));
    expect(history(state).map((t) => t.who)).toEqual([
      'you',
      'stylist',
      'you',
      'stylist',
    ]);
  });

  it('**never sends a half-written reply**', () => {
    // It would have the model continue its own unfinished sentence.
    let state = reply('done');
    state = asked(state, 'next');
    state = streamed(state, 'still writ');
    expect(history(state).some((t) => t.text.includes('still writ'))).toBe(
      false,
    );
  });

  it('leaves out a failed turn', () => {
    let state = asked(begin(), 'q');
    state = failed(state);
    expect(history(state).some((t) => t.who === 'stylist')).toBe(false);
  });

  it('is capped', () => {
    let state = begin();
    for (let i = 0; i < 12; i += 1) {
      state = asked(state, `q${i}`);
      state = settled(streamed(state, `a${i}`));
    }
    expect(history(state, 10)).toHaveLength(10);
  });
});

describe('offering a try-on', () => {
  function stylistTurn(over: Partial<Turn>): Turn {
    return { id: 't', who: 'stylist', text: 'x', ...over };
  }

  it('is offered when there is something to wear', () => {
    expect(canTryOn(stylistTurn({ verdict: VERDICT }))).toBe(true);
  });

  it('is offered for pieces they would have to buy', () => {
    expect(
      canTryOn(
        stylistTurn({
          verdict: { hasMatch: false, using: [], missing: ['boots'] },
        }),
      ),
    ).toBe(true);
  });

  it('is not offered with nothing behind it', () => {
    expect(
      canTryOn(
        stylistTurn({ verdict: { hasMatch: false, using: [], missing: [] } }),
      ),
    ).toBe(false);
  });

  it('is not offered twice for the same turn', () => {
    expect(canTryOn(stylistTurn({ verdict: VERDICT, renderId: 'r' }))).toBe(
      false,
    );
  });

  it('is not offered while the reply is still arriving', () => {
    expect(canTryOn(stylistTurn({ verdict: VERDICT, streaming: true }))).toBe(
      false,
    );
  });

  it('is never offered on the person own turn', () => {
    expect(canTryOn({ id: 't', who: 'you', text: 'hi' })).toBe(false);
  });
});

describe('busy', () => {
  it('is true only while something is streaming', () => {
    expect(busy(begin())).toBe(false);
    expect(busy(asked(begin(), 'q'))).toBe(true);
    expect(busy(reply('done'))).toBe(false);
  });
});
