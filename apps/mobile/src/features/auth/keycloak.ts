import * as AuthSession from 'expo-auth-session';

import { BRAND } from '@/branding';

/**
 * Where Keycloak lives, and what we are allowed to ask it for.
 *
 * Endpoints are derived from the issuer rather than listed, because Keycloak
 * moved them once already: the `/auth` path prefix was dropped in Keycloak 17,
 * and every hardcoded URL written before that broke. The issuer is the one
 * value an operator configures, and everything else hangs off it.
 *
 * Discovery is *not* fetched at runtime. It would be the orthodox choice, but
 * it costs a network round trip on the sign-in path, and these three paths are
 * fixed by the OIDC spec for Keycloak's realm layout. The token endpoint is
 * the only one that matters for correctness, and a wrong one fails loudly on
 * first use rather than silently.
 */

/** Issuer, e.g. `http://localhost:55080/realms/luxish`. */
const ISSUER =
  process.env.EXPO_PUBLIC_KEYCLOAK_ISSUER ?? 'http://localhost:55080/realms/luxish';

/** Must match the realm's `clientId` for the public mobile client. */
export const CLIENT_ID = process.env.EXPO_PUBLIC_KEYCLOAK_CLIENT_ID ?? 'luxish-mobile';

const base = ISSUER.replace(/\/$/, '');

export const discovery: AuthSession.DiscoveryDocument = {
  authorizationEndpoint: `${base}/protocol/openid-connect/auth`,
  tokenEndpoint: `${base}/protocol/openid-connect/token`,
  endSessionEndpoint: `${base}/protocol/openid-connect/logout`,
  revocationEndpoint: `${base}/protocol/openid-connect/revoke`,
};

export const ISSUER_URL = base;

/**
 * Scopes requested at sign-in.
 *
 * `offline_access` is what earns a refresh token that outlives the browser
 * session, which is the difference between signing in once and signing in
 * every morning. The realm must allow it as an optional client scope or
 * Keycloak silently returns a short-lived refresh token instead.
 */
export const SCOPES = ['openid', 'profile', 'email', 'offline_access'];

/**
 * Where Keycloak sends the browser back to.
 *
 * `makeRedirectUri` returns different shapes per environment, and all of them
 * have to be registered on the client or Keycloak refuses with
 * `invalid_redirect_uri` before the user ever sees a login form:
 *
 * - a dev build or a store build gets `luxish://callback`, from the scheme in
 *   `branding.config.js`;
 * - Expo Go gets `exp://<host>:<port>/--/callback`, and the host changes every
 *   time a tunnel restarts, which is why the dev realm registers a pattern
 *   rather than a literal.
 *
 * The `auth.expo.io` proxy that used to paper over this was removed in SDK 53,
 * so there is no longer a stable third shape to fall back on.
 */
export function redirectUri(): string {
  return AuthSession.makeRedirectUri({ scheme: BRAND.scheme, path: 'callback' });
}

/**
 * Identity provider to jump straight to, skipping Keycloak's own form.
 *
 * Keycloak reads `kc_idp_hint` and forwards to that provider. Passing
 * `'google'` is what makes "Continue with Google" one tap instead of two.
 */
export const GOOGLE_IDP_HINT = 'google';
