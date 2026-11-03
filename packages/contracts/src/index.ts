/**
 * The typed API surface, generated from the backend's own OpenAPI document.
 *
 * `schema.d.ts` is generated — never hand-edited. `npm run check` regenerates it and
 * fails on a diff, so a backend contract change cannot land without the client being
 * regenerated alongside it. That is the whole point of this package: the mobile app
 * should fail to compile when the API changes under it, rather than fail at runtime
 * in someone's hands.
 */

import createClient, { type Middleware } from 'openapi-fetch';

import type { paths } from './schema';

export type { paths } from './schema';
export type { components, operations } from './schema';

/** Supplies the current bearer token, or null when signed out. */
export type TokenProvider = () => Promise<string | null> | string | null;

export interface ClientOptions {
  baseUrl: string;
  /** Called before every request. Keep it cheap — it runs on the hot path. */
  getToken?: TokenProvider;
  /**
   * Invoked when the API rejects our token, and awaited.
   *
   * Return `true` to say "I obtained a fresh token, retry the request once".
   * Return `false` (or nothing) to say the session is genuinely over, in which
   * case the 401 is thrown as normal. This package deliberately does not know
   * how to re-authenticate; it only knows to ask once and to retry at most
   * once, so a server that answers 401 to everything cannot loop.
   */
  onUnauthorized?: () => void | boolean | Promise<void | boolean>;
  /** Overridable for tests. */
  fetch?: typeof globalThis.fetch;
}

/**
 * The error shape the API actually returns. Every failure carries a stable `code`
 * and the request id, because "something went wrong" is not a supportable bug report.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly detail: unknown;

  constructor(args: {
    status: number;
    code: string;
    message: string;
    requestId: string | null;
    detail?: unknown;
  }) {
    super(args.message);
    this.name = 'ApiError';
    this.status = args.status;
    this.code = args.code;
    this.requestId = args.requestId;
    this.detail = args.detail;
  }

  /** True when retrying the identical request could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }

  /** True when the caller supplied something wrong — retrying will not help. */
  get isClientFault(): boolean {
    return this.status >= 400 && this.status < 500 && this.status !== 429;
  }
}

const REQUEST_ID_HEADER = 'x-request-id';

function authMiddleware(options: ClientOptions): Middleware {
  return {
    async onRequest({ request }) {
      const token = await options.getToken?.();
      if (token) request.headers.set('Authorization', `Bearer ${token}`);
      return request;
    },

    async onResponse({ request, response }) {
      // Nothing is returned on the happy path, and that is deliberate.
      //
      // `openapi-fetch` treats any truthy return as a replacement response and
      // rejects it unless it satisfies `instanceof Response`. The object a
      // platform `fetch` hands back does not always satisfy that check against
      // the `Response` binding the library resolves — React Native is one
      // place it does not — so handing the untouched response straight back
      // turned every successful call into
      // "onResponse: must return new Response() when modifying the response".
      // Returning nothing says "unmodified", which is what we mean.
      if (response.ok) return;

      const requestId = response.headers.get(REQUEST_ID_HEADER);

      // A 401 means our token is gone or rejected. Tell the app once, here,
      // rather than making every call site recognise it.
      //
      // If the app says it recovered, replay the request once with the new
      // token. Without this, a token that expires mid-session surfaces as a
      // failed request even though the very next call would have worked, so
      // the user sees a spurious error and a refresh that fixed nothing they
      // can see. The retry is bounded to one attempt by construction: the
      // replayed request is issued directly rather than through the
      // middleware, so it cannot re-enter this branch.
      if (response.status === 401) {
        const recovered = await options.onUnauthorized?.();
        if (recovered === true) {
          const retried = request.clone();
          const token = await options.getToken?.();
          if (token) retried.headers.set('Authorization', `Bearer ${token}`);
          const replayed = await (options.fetch ?? globalThis.fetch)(retried);
          // Rebuilt rather than handed back as-is, for the same reason the
          // happy path returns nothing: this value *is* a replacement, so it
          // has to pass `instanceof Response`, and only a response built from
          // the constructor in scope here reliably does.
          //
          // Returned whether or not it succeeded: a second 401 is reported to
          // the caller as a failed request, which is the correct outcome.
          return new Response(await replayed.text(), {
            status: replayed.status,
            statusText: replayed.statusText,
            headers: replayed.headers,
          });
        }
      }

      // Read the body defensively: an error response is exactly when a body is most
      // likely to be absent or not be JSON.
      let payload: Record<string, unknown> = {};
      try {
        const text = await response.clone().text();
        if (text) payload = JSON.parse(text) as Record<string, unknown>;
      } catch {
        // Leave payload empty; the status and request id still identify the failure.
      }

      throw new ApiError({
        status: response.status,
        code: typeof payload.code === 'string' ? payload.code : `http_${response.status}`,
        message:
          typeof payload.message === 'string'
            ? payload.message
            : `${response.status} ${response.statusText}`,
        requestId,
        detail: payload.detail,
      });
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

export function createApiClient(options: ClientOptions) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl.replace(/\/+$/, ''),
    fetch: options.fetch,
    headers: { 'Content-Type': 'application/json' },
  });
  client.use(authMiddleware(options));
  return client;
}
