/**
 * The app's single API client.
 *
 * Typed end to end from the backend's OpenAPI document, so a contract change breaks
 * the build rather than a user's session. No screen constructs a client of its own —
 * that is how a second base URL or an unauthenticated call sneaks in.
 */

import { ApiError, createApiClient, type ApiClient } from '@fashion/contracts';
import { Platform } from 'react-native';

import { secureSession } from '@/storage/secure';

export { ApiError };
export type { ApiClient };

/**
 * `localhost` is the device's own loopback, not the developer's machine, so an
 * Android emulator needs the special 10.0.2.2 alias and a physical device needs the
 * host's LAN address. Getting this wrong presents as an inexplicable network error,
 * so it is resolved once, here.
 */
function defaultBaseUrl(): string {
  const configured = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (configured) return configured;
  if (Platform.OS === 'android') return 'http://10.0.2.2:8010';
  return 'http://127.0.0.1:8010';
}

export const API_BASE_URL = defaultBaseUrl();

/** Set by the auth layer so a 401 can clear the session exactly once. */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export const api: ApiClient = createApiClient({
  baseUrl: API_BASE_URL,
  getToken: () => secureSession.validAccessToken(),
  onUnauthorized: () => {
    // Clear first, then notify: the handler may navigate, and navigating with a
    // stale token still in the keychain would re-authenticate into a dead session.
    void secureSession.clear();
    onUnauthorized?.();
  },
});

/**
 * Turns any thrown value into something a screen can show a person.
 *
 * Deliberately not a generic "Something went wrong": the brief requires retry and
 * offline states to be distinguishable, and that distinction has to survive the
 * trip from the error to the UI.
 */
export function describeError(error: unknown): {
  title: string;
  body: string;
  kind: 'offline' | 'auth' | 'client' | 'server' | 'unknown';
  retryable: boolean;
} {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return {
        kind: 'auth',
        retryable: false,
        title: 'Please sign in again',
        body: 'Your session has expired.',
      };
    }
    if (error.status === 429) {
      return {
        kind: 'server',
        retryable: true,
        title: 'Too many requests',
        body: 'Give it a moment and try again.',
      };
    }
    if (error.isClientFault) {
      return {
        kind: 'client',
        retryable: false,
        title: 'That did not work',
        // The code is shown because it is the one thing that makes a support
        // conversation possible.
        body: `${error.message} (${error.code})`,
      };
    }
    return {
      kind: 'server',
      retryable: true,
      title: 'The server had a problem',
      body: error.requestId
        ? `Please try again. Reference: ${error.requestId}`
        : 'Please try again.',
    };
  }

  // openapi-fetch surfaces a transport failure as a plain TypeError.
  if (error instanceof TypeError) {
    return {
      kind: 'offline',
      retryable: true,
      title: 'No connection',
      body: `Could not reach ${API_BASE_URL}. Check your connection, or that the API is running.`,
    };
  }

  return {
    kind: 'unknown',
    retryable: true,
    title: 'Something unexpected happened',
    body: error instanceof Error ? error.message : String(error),
  };
}
