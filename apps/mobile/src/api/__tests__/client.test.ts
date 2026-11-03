/**
 * The client's job is to make failures distinguishable.
 *
 * "Something went wrong" is the failure these tests exist to prevent: §3 requires
 * retry and offline states to be separate, and that distinction has to survive the
 * trip from a thrown value to the UI. Each case below is a state a user can actually
 * reach.
 */

import { ApiError, createApiClient } from '@fashion/contracts';

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));

/* eslint-disable import/first */
import { describeError } from '@/api/client';
/* eslint-enable import/first */

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('describeError', () => {
  it('separates offline from server failure', () => {
    // openapi-fetch surfaces a transport failure as a plain TypeError.
    const offline = describeError(new TypeError('Network request failed'));
    expect(offline.kind).toBe('offline');
    expect(offline.retryable).toBe(true);
    // The base URL is named, because "no connection" on a simulator usually means
    // the wrong host, not an actual network problem.
    expect(offline.body).toContain('http');

    const server = describeError(
      new ApiError({ status: 503, code: 'unavailable', message: 'down', requestId: 'req-1' }),
    );
    expect(server.kind).toBe('server');
    expect(server.retryable).toBe(true);
  });

  it('surfaces the request id on a server fault so support is possible', () => {
    const described = describeError(
      new ApiError({ status: 500, code: 'boom', message: 'x', requestId: 'req-abc' }),
    );
    expect(described.body).toContain('req-abc');
  });

  it('treats 401 as needing sign-in rather than retry', () => {
    const described = describeError(
      new ApiError({ status: 401, code: 'unauthorized', message: 'no', requestId: null }),
    );
    expect(described.kind).toBe('auth');
    expect(described.retryable).toBe(false);
  });

  it('treats 429 as retryable even though it is a 4xx', () => {
    const described = describeError(
      new ApiError({ status: 429, code: 'rate_limited', message: 'slow', requestId: null }),
    );
    expect(described.retryable).toBe(true);
    expect(described.kind).toBe('server');
  });

  it('shows the error code on a client fault, since that is what support needs', () => {
    const described = describeError(
      new ApiError({
        status: 409,
        code: 'identity_link_required',
        message: 'Link required',
        requestId: null,
      }),
    );
    expect(described.retryable).toBe(false);
    expect(described.body).toContain('identity_link_required');
  });
});

describe('client behaviour', () => {
  it('attaches a bearer token when one is available', async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: 'https://api.test',
      getToken: () => 'token-123',
      fetch: async (input) => {
        seen.push(input as Request);
        return jsonResponse(200, { status: 'ok' });
      },
    });

    await client.GET('/healthz');
    expect(seen[0].headers.get('Authorization')).toBe('Bearer token-123');
  });

  it('sends no Authorization header when signed out', async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: 'https://api.test',
      getToken: () => null,
      fetch: async (input) => {
        seen.push(input as Request);
        return jsonResponse(200, { status: 'ok' });
      },
    });

    await client.GET('/healthz');
    // An empty bearer is worse than none: it reads as a malformed token.
    expect(seen[0].headers.get('Authorization')).toBeNull();
  });

  it('throws a typed ApiError carrying code and request id', async () => {
    const client = createApiClient({
      baseUrl: 'https://api.test',
      fetch: async () =>
        jsonResponse(409, { code: 'identity_link_required', message: 'Link required' }, {
          'x-request-id': 'req-99',
        }),
    });

    await expect(client.GET('/healthz')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'identity_link_required',
      requestId: 'req-99',
    });
  });

  it('notifies the app exactly once on 401 so the session is cleared centrally', async () => {
    const onUnauthorized = jest.fn();
    const client = createApiClient({
      baseUrl: 'https://api.test',
      onUnauthorized,
      fetch: async () => jsonResponse(401, { code: 'unauthorized', message: 'no' }),
    });

    await expect(client.GET('/healthz')).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('survives an error response with no body or a non-JSON body', async () => {
    // Exactly when a body is most likely to be missing or HTML from a proxy.
    const client = createApiClient({
      baseUrl: 'https://api.test',
      fetch: async () => new Response('<html>502</html>', { status: 502 }),
    });

    await expect(client.GET('/healthz')).rejects.toMatchObject({
      status: 502,
      code: 'http_502',
    });
  });

  it('does not treat a trailing slash on the base URL as a different host', async () => {
    const seen: string[] = [];
    const client = createApiClient({
      baseUrl: 'https://api.test/',
      fetch: async (input) => {
        seen.push((input as Request).url);
        return jsonResponse(200, { status: 'ok' });
      },
    });

    await client.GET('/healthz');
    expect(seen[0]).toBe('https://api.test/healthz');
  });
});

/**
 * A response that behaves like the platform's but is **not** an instance of the
 * `Response` that `openapi-fetch`'s `instanceof` check resolves to.
 *
 * This is the React Native case, and it is the entire reason the bug it pins
 * reached a device: under Node, `new Response()` satisfies that check, so the
 * suite stayed green while every successful call on a phone threw
 * "onResponse: must return new Response() when modifying the response".
 */
class ForeignResponse {
  readonly status: number;
  readonly statusText = '';
  readonly headers: Headers;
  readonly body = null;
  readonly #text: string;

  constructor(text: string, init: { status: number; headers?: Record<string, string> }) {
    this.#text = text;
    this.status = init.status;
    this.headers = new Headers(init.headers ?? {});
  }

  get ok(): boolean {
    return this.status >= 200 && this.status < 300;
  }

  async text(): Promise<string> {
    return this.#text;
  }

  async json(): Promise<unknown> {
    return JSON.parse(this.#text);
  }

  clone(): ForeignResponse {
    return new ForeignResponse(this.#text, { status: this.status });
  }
}

function foreignJson(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new ForeignResponse(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  }) as unknown as Response;
}

describe('responses from a runtime whose Response is not the global one', () => {
  it('returns the data rather than throwing', async () => {
    const client = createApiClient({
      baseUrl: 'https://api.test',
      fetch: async () => foreignJson(200, { status: 'ok' }),
    });

    // Before the fix this rejected with "onResponse: must return new
    // Response() when modifying the response", because the middleware handed
    // the untouched response straight back and it failed `instanceof`.
    const result = await client.GET('/healthz');
    expect(result.data).toEqual({ status: 'ok' });
    expect(result.error).toBeUndefined();
  });

  it('still reports a failure as a typed ApiError', async () => {
    const client = createApiClient({
      baseUrl: 'https://api.test',
      fetch: async () =>
        foreignJson(409, { code: 'identity_link_required', message: 'Link required' }, {
          'x-request-id': 'req-rn',
        }),
    });

    await expect(client.GET('/healthz')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      code: 'identity_link_required',
      requestId: 'req-rn',
    });
  });

  it('replays once after a recovered 401 and hands back a usable response', async () => {
    let call = 0;
    const client = createApiClient({
      baseUrl: 'https://api.test',
      getToken: () => (call === 0 ? 'stale' : 'fresh'),
      onUnauthorized: async () => true,
      fetch: async () => {
        call += 1;
        return call === 1
          ? foreignJson(401, { code: 'unauthorized', message: 'no' })
          : foreignJson(200, { status: 'ok' });
      },
    });

    const result = await client.GET('/healthz');
    expect(result.data).toEqual({ status: 'ok' });
    expect(call).toBe(2);
  });
});
