/**
 * Where a notification goes when somebody taps it.
 *
 * **One table, read by both kinds of notification.** A notice in the
 * inbox and a banner on the lock screen are the same event seen twice,
 * and they must land in the same place: two routing rules is two
 * chances for one of them to be wrong, which is exactly how this
 * started.
 *
 * The server names a destination where it can - `target` on an inbox
 * notification, `deep_link` on a queued push - because the server
 * knows which fit or which run the notice is about. This is the
 * fallback for when it does not, and the guard for when what it sends
 * is not a route.
 */

/** Where each kind lands when the server names nothing specific. */
const BY_KIND: Record<string, string> = {
  wardrobe_sorted: '/wardrobe',
  stylist_ready: '/stylist',
  fit_reactions: '/',
  // A finished shot is on the studio's own shelf.
  studio_ready: '/studio',
  // Everything a person sent or was sent.
  message: '/messages',
  comment: '/',
  // These two normally arrive with a `deep_link` naming the fit or
  // the follower, and these are where they land when it is missing.
  // Not Discover: "somebody kept your fit" that opens a feed of
  // strangers' clothes reads as a bug, where your own shelf of fits
  // at least contains the one they kept.
  fit_saved: '/profile',
  new_follower: '/people/followers',
};

/** Where a tap goes when nothing else is known. */
const FALLBACK = '/inbox';

/**
 * A route group can never appear in a path.
 *
 * `(tabs)` organises files; it is not a segment. Two server targets
 * carried it - `/(tabs)/wardrobe` and `/(tabs)/stylist` - and both
 * tapped through to nothing. Fixed at the source, and refused here
 * too: this runs on whatever a server sends, including an older one.
 */
function isRoutable(path: string): boolean {
  return path.startsWith('/') && !path.includes('(') && !path.includes('..');
}

/**
 * The path to open for a notification.
 *
 * `named` is whatever the server supplied. `kind` is the event. One
 * of them always produces somewhere to go: a tap that does nothing is
 * indistinguishable from a tap that was not registered, which is the
 * worst thing a notification can do.
 */
export function routeFor(input: {
  named?: string | null;
  kind?: string | null;
}): string {
  const named = input.named?.trim();
  if (named && isRoutable(named)) return named;
  const byKind = input.kind ? BY_KIND[input.kind] : undefined;
  return byKind ?? FALLBACK;
}

export { BY_KIND as NOTIFICATION_ROUTES, FALLBACK as NOTIFICATION_FALLBACK };
