/**
 * Reading the stylist's answer off a stream.
 *
 * Every test here splits the response at a hostile boundary, because
 * that is what a real network does: a chunk ends mid-frame, mid-JSON
 * or mid-word, and a reader that assumes otherwise drops whatever
 * was crossing the boundary. Dropping a token is a missing word in
 * somebody's answer; dropping the verdict frame is the whole feature
 * silently not happening.
 */

import { askStylist, type ShoppableItem } from '@/features/stylist/ask';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('@/features/auth/session', () => ({
  accessToken: jest.fn(async () => 'a-token'),
}));
jest.mock('@/api/client', () => ({ API_BASE_URL: 'http://example.invalid' }));

const { fetch: mockFetch } = jest.requireMock('expo/fetch') as {
  fetch: jest.Mock;
};
const { accessToken } = jest.requireMock('@/features/auth/session') as {
  accessToken: jest.Mock;
};

/** A response whose body yields exactly these chunks. */
function streaming(chunks: string[], ok = true) {
  const encoder = new TextEncoder();
  let at = 0;
  return {
    ok,
    body: {
      getReader: () => ({
        read: async () =>
          at < chunks.length
            ? { done: false, value: encoder.encode(chunks[at++]) }
            : { done: true, value: undefined },
        releaseLock: () => {},
      }),
    },
  };
}

function frame(payload: object): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

beforeEach(() => {
  mockFetch.mockReset();
  accessToken.mockResolvedValue('a-token');
});

it('delivers tokens in order', async () => {
  mockFetch.mockResolvedValue(
    streaming([
      frame({ event: 'token', text: 'Yes, ' }),
      frame({ event: 'token', text: 'you do.' }),
      frame({ event: 'done' }),
    ]),
  );
  const got: string[] = [];
  await askStylist({ question: 'q' }, { onToken: (t) => got.push(t) });
  expect(got.join('')).toBe('Yes, you do.');
});

it('survives a chunk boundary inside a frame', async () => {
  // The commonest real split, and the one that drops a token.
  const whole = frame({ event: 'token', text: 'hello' });
  const cut = Math.floor(whole.length / 2);
  mockFetch.mockResolvedValue(
    streaming([whole.slice(0, cut), whole.slice(cut), frame({ event: 'done' })]),
  );
  const got: string[] = [];
  await askStylist({ question: 'q' }, { onToken: (t) => got.push(t) });
  expect(got.join('')).toBe('hello');
});

it('survives several frames arriving in one chunk', async () => {
  mockFetch.mockResolvedValue(
    streaming([
      frame({ event: 'token', text: 'a' }) +
        frame({ event: 'token', text: 'b' }) +
        frame({ event: 'token', text: 'c' }),
      frame({ event: 'done' }),
    ]),
  );
  const got: string[] = [];
  await askStylist({ question: 'q' }, { onToken: (t) => got.push(t) });
  expect(got.join('')).toBe('abc');
});

it('reports the verdict', async () => {
  mockFetch.mockResolvedValue(
    streaming([
      frame({
        event: 'verdict',
        has_match: true,
        using: ['g1', 'g2'],
        missing: [],
      }),
      frame({ event: 'done' }),
    ]),
  );
  const seen: unknown[] = [];
  await askStylist({ question: 'q' }, { onVerdict: (v) => seen.push(v) });
  expect(seen).toEqual([{ hasMatch: true, using: ['g1', 'g2'], missing: [] }]);
});

it('passes shopping results through', async () => {
  const item: ShoppableItem = {
    product_id: 'p1',
    title: 'Cream trousers',
    retailer: 'Somewhere',
    url: null,
    match_label: 'similar_style',
  };
  mockFetch.mockResolvedValue(
    streaming([
      frame({ event: 'shopping', items: [item] }),
      frame({ event: 'done' }),
    ]),
  );
  let got: ShoppableItem[] = [];
  await askStylist({ question: 'q' }, { onShopping: (i) => (got = i) });
  expect(got).toEqual([item]);
});

it('reports a queued avatar', async () => {
  mockFetch.mockResolvedValue(
    streaming([
      frame({ event: 'render', render_id: 'r1' }),
      frame({ event: 'done' }),
    ]),
  );
  const seen: string[] = [];
  await askStylist({ question: 'q' }, { onRender: (r) => seen.push(r) });
  expect(seen).toEqual(['r1']);
});

it('skips one unreadable frame rather than failing the answer', async () => {
  mockFetch.mockResolvedValue(
    streaming([
      frame({ event: 'token', text: 'good' }),
      'data: {not json at all\n\n',
      frame({ event: 'token', text: ' still good' }),
      frame({ event: 'done' }),
    ]),
  );
  const got: string[] = [];
  const errors: number[] = [];
  await askStylist(
    { question: 'q' },
    { onToken: (t) => got.push(t), onError: () => errors.push(1) },
  );
  expect(got.join('')).toBe('good still good');
  expect(errors).toHaveLength(0);
});

it('reports an error status rather than hanging', async () => {
  mockFetch.mockResolvedValue(streaming([], false));
  let failed = false;
  await askStylist({ question: 'q' }, { onError: () => (failed = true) });
  expect(failed).toBe(true);
});

it('reports a thrown request rather than hanging', async () => {
  mockFetch.mockRejectedValue(new Error('offline'));
  let failed = false;
  await askStylist({ question: 'q' }, { onError: () => (failed = true) });
  expect(failed).toBe(true);
});

it('does not ask without a token', async () => {
  accessToken.mockResolvedValue(null);
  let failed = false;
  await askStylist({ question: 'q' }, { onError: () => (failed = true) });
  expect(failed).toBe(true);
  expect(mockFetch).not.toHaveBeenCalled();
});

it('sends the pin it was opened from', async () => {
  mockFetch.mockResolvedValue(streaming([frame({ event: 'done' })]));
  await askStylist({ question: 'q', postId: 'post-1' }, {});
  const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
  expect(body).toEqual({
    question: 'q',
    post_id: 'post-1',
    garment_id: null,
    history: [],
  });
});

it('sends the garment the question points at', async () => {
  // **The field whose absence was the bug.** The composer could
  // attach one of their own clothes and this request could not carry
  // it, so "What pants and accessories can I wear with this?" reached
  // the server as those words and a wardrobe list. The model guessed
  // which garment "this" was, answered about the wrong one, and the
  // figure beside the answer wore no top at all.
  mockFetch.mockResolvedValue(streaming([frame({ event: 'done' })]));
  await askStylist({ question: 'what goes with this?', garmentId: 'g-7' }, {});
  const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
  expect(body.garment_id).toBe('g-7');
});

it('sends a null garment when the question points at nothing', async () => {
  mockFetch.mockResolvedValue(streaming([frame({ event: 'done' })]));
  await askStylist({ question: 'what should I wear?' }, {});
  const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
  expect(body.garment_id).toBeNull();
});

it('sends a null pin when there is none', async () => {
  mockFetch.mockResolvedValue(streaming([frame({ event: 'done' })]));
  await askStylist({ question: 'q' }, {});
  const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
  expect(body.post_id).toBeNull();
});

it('sends what has already been said', () => {
  // A follow-up only reads as one if the model can see the turn it
  // is following.
  mockFetch.mockResolvedValue(streaming([frame({ event: 'done' })]));
  return askStylist(
    {
      question: 'and with boots?',
      history: [
        { who: 'you', text: 'what goes with this?' },
        { who: 'stylist', text: 'The cream trousers.' },
      ],
    },
    {},
  ).then(() => {
    const body = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(body.history).toHaveLength(2);
    expect(body.history[0].who).toBe('you');
  });
});
