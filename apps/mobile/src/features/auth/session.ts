import * as AuthSession from 'expo-auth-session';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useSyncExternalStore } from 'react';

import { secureSession, type StoredSession } from '@/storage/secure';

import {
  CLIENT_ID,
  GOOGLE_IDP_HINT,
  SCOPES,
  discovery,
  redirectUri,
} from '@/features/auth/keycloak';

/**
 * Sign-in, refresh and sign-out against Keycloak.
 *
 * Authorization Code with PKCE, which is the only flow a public native client
 * may use: there is no client secret, because anything shipped in an app
 * binary is readable, and PKCE is what replaces it. `expo-auth-session`
 * generates and verifies the challenge, so the one thing this module must not
 * do is pass a secret or fall back to the implicit flow.
 *
 * The system browser does the work rather than a WebView. That is a security
 * requirement, not a preference (RFC 8252): a WebView lets the app read the
 * user's Google password as they type it, which is exactly what federated
 * sign-in exists to avoid, and Google refuses WebView traffic for that reason.
 *
 * Tokens never leave `expo-secure-store`. Nothing here logs a token, and the
 * refresh path replaces the stored pair atomically so a failed refresh cannot
 * leave a valid access token beside a dead refresh token.
 */

// Lets the browser result close the popup and return to the app on web, and is
// a no-op on native. Must run once at module scope.
WebBrowser.maybeCompleteAuthSession();

export type AuthState =
  | { status: 'loading' }
  | { status: 'signedOut' }
  | { status: 'signedIn'; expiresAt: number | null };

let state: AuthState = { status: 'loading' };
const listeners = new Set<() => void>();

function publish(next: AuthState): void {
  state = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Seconds-to-milliseconds, guarding the case where the server omits it. */
function expiryFrom(expiresIn: number | undefined, now: number): number | null {
  return typeof expiresIn === 'number' ? now + expiresIn * 1000 : null;
}

async function store(
  tokens: {
    accessToken: string;
    refreshToken?: string | null;
    expiresIn?: number;
  },
  now = Date.now(),
): Promise<void> {
  const session: StoredSession = {
    accessToken: tokens.accessToken,
    refreshToken: tokens.refreshToken ?? null,
    expiresAt: expiryFrom(tokens.expiresIn, now),
  };
  await secureSession.save(session);
  publish({ status: 'signedIn', expiresAt: session.expiresAt });
}

/**
 * Read what is already on the device. Called once at launch.
 *
 * A stored-but-expired access token is not signed out: the refresh token may
 * still be good, so the state is reported as signed in and the refresh happens
 * on first use. Treating expiry as sign-out would log people out every time
 * they opened the app after five minutes away.
 */
export async function restore(): Promise<AuthState> {
  const session = await secureSession.load();
  const next: AuthState =
    session === null
      ? { status: 'signedOut' }
      : { status: 'signedIn', expiresAt: session.expiresAt };
  publish(next);
  return next;
}

export class AuthError extends Error {
  constructor(
    message: string,
    readonly code: 'cancelled' | 'dismissed' | 'failed',
  ) {
    super(message);
    this.name = 'AuthError';
  }
}

export interface SignInOptions {
  /** Jump straight to Google rather than Keycloak's own form. */
  withGoogle?: boolean;
  /**
   * Force the account chooser even when Google has a live session.
   *
   * Without it, someone signed into the wrong Google account cannot get out of
   * it from inside the app, which is a support ticket rather than a bug report.
   */
  selectAccount?: boolean;
}

/**
 * Open the browser, complete PKCE, and persist the result.
 *
 * Throws `AuthError` with `cancelled` when the user backs out, which callers
 * should treat as a non-event and not surface as a failure.
 */
export async function signIn(options: SignInOptions = {}): Promise<void> {
  const extraParams: Record<string, string> = {};
  if (options.withGoogle) extraParams.kc_idp_hint = GOOGLE_IDP_HINT;
  if (options.selectAccount) extraParams.prompt = 'select_account';

  const request = new AuthSession.AuthRequest({
    clientId: CLIENT_ID,
    scopes: SCOPES,
    redirectUri: redirectUri(),
    usePKCE: true,
    responseType: AuthSession.ResponseType.Code,
    extraParams,
  });

  const result = await request.promptAsync(discovery);

  if (result.type === 'cancel' || result.type === 'dismiss') {
    throw new AuthError('Sign-in was cancelled.', 'cancelled');
  }
  if (result.type !== 'success') {
    throw new AuthError('Sign-in did not complete.', 'failed');
  }
  if (result.params.error) {
    // Keycloak puts the reason here. `invalid_redirect_uri` is overwhelmingly
    // the one seen in development, and it means the realm does not list the
    // URI this build produced.
    throw new AuthError(
      result.params.error_description ?? result.params.error,
      'failed',
    );
  }

  const now = Date.now();
  const tokens = await AuthSession.exchangeCodeAsync(
    {
      clientId: CLIENT_ID,
      code: result.params.code,
      redirectUri: redirectUri(),
      // The verifier the request generated. Omitting it is the classic PKCE
      // mistake: Keycloak answers 400 `invalid_grant` with no further detail.
      extraParams: { code_verifier: request.codeVerifier ?? '' },
    },
    discovery,
  );

  await store(
    {
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
      expiresIn: tokens.expiresIn,
    },
    now,
  );
}

/**
 * The refresh in flight, if any.
 *
 * Keycloak rotates refresh tokens: presenting one consumes it and returns a
 * new one. So two concurrent refreshes are not merely wasteful, they are
 * destructive — the first consumes the token, the second presents a token
 * that no longer exists, fails, and tears down a session that was perfectly
 * healthy. Anything that uploads several things at once hits this on the
 * first expiry, which is exactly how it was found: a multi-photo upload
 * reported "sign in to upload" to a signed-in user.
 *
 * One promise, shared by every caller, so the rotation happens once.
 */
let inFlightRefresh: Promise<string | null> | null = null;

/**
 * Swap the refresh token for a new pair.
 *
 * Returns the new access token, or null when the refresh token is gone or
 * rejected, which is a real sign-out: the session was revoked, the user
 * changed their password, or the token simply aged out. Callers should send
 * the user to sign-in rather than retrying.
 */
export async function refresh(): Promise<string | null> {
  // Join the refresh already running rather than starting a competing one.
  if (inFlightRefresh) return inFlightRefresh;
  inFlightRefresh = performRefresh().finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}

async function performRefresh(): Promise<string | null> {
  const session = await secureSession.load();
  if (!session?.refreshToken) {
    await signOutLocally();
    return null;
  }

  const now = Date.now();
  try {
    const tokens = await AuthSession.refreshAsync(
      { clientId: CLIENT_ID, refreshToken: session.refreshToken },
      discovery,
    );
    await store(
      {
        accessToken: tokens.accessToken,
        // Keycloak rotates refresh tokens by default. Keeping the old one on a
        // response that omits a new one is what causes a session to die a few
        // minutes later for no visible reason.
        refreshToken: tokens.refreshToken ?? session.refreshToken,
        expiresIn: tokens.expiresIn,
      },
      now,
    );
    return tokens.accessToken;
  } catch {
    await signOutLocally();
    return null;
  }
}

/**
 * A usable access token, refreshing first if the stored one is close to expiry.
 *
 * This is what the API client calls before every request. `validAccessToken`
 * applies a 30-second margin, so a token that would expire mid-flight counts
 * as already expired.
 */
export async function accessToken(): Promise<string | null> {
  const current = await secureSession.validAccessToken();
  if (current) return current;
  return refresh();
}

/** Forget the tokens. Does not tell Keycloak. */
async function signOutLocally(): Promise<void> {
  await secureSession.clear();
  publish({ status: 'signedOut' });
}

/**
 * Sign out here and at Keycloak.
 *
 * Local-only sign-out is not enough: the Keycloak session cookie survives in
 * the system browser, so the next sign-in silently reuses it and the user
 * appears unable to switch accounts. `end_session_endpoint` with the refresh
 * token is what actually ends it.
 *
 * The local clear happens regardless of whether Keycloak could be reached,
 * because a user who asked to sign out must be signed out on this device even
 * when offline.
 */
export async function signOut(): Promise<void> {
  const session = await secureSession.load();
  await signOutLocally();

  if (!session?.refreshToken || !discovery.endSessionEndpoint) return;
  try {
    await fetch(discovery.endSessionEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: CLIENT_ID,
        refresh_token: session.refreshToken,
      }).toString(),
    });
  } catch {
    // Already signed out locally; a network failure here is not worth
    // surfacing or retrying.
  }
}

/** Current auth state, re-rendering on change. */
export function useAuth(): AuthState & {
  signIn: typeof signIn;
  signOut: typeof signOut;
} {
  const current = useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  );

  useEffect(() => {
    if (state.status === 'loading') void restore();
  }, []);

  // Inline wrappers rather than `useCallback(signIn, [])`: the lint rule
  // cannot verify the dependencies of a function it did not see declared, and
  // both are module-level and already stable.
  return {
    ...current,
    signIn: useCallback((options?: SignInOptions) => signIn(options), []),
    signOut: useCallback(() => signOut(), []),
  };
}

/** Test seam: reset module state between cases. */
export function __resetAuthState(): void {
  state = { status: 'loading' };
  listeners.clear();
}
