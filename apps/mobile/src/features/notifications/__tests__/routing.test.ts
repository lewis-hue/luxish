import {
  NOTIFICATION_FALLBACK,
  NOTIFICATION_ROUTES,
  routeFor,
} from '@/features/notifications/routing';

describe('routeFor', () => {
  it('goes where the server said', () => {
    expect(routeFor({ named: '/fit/abc123', kind: 'fit_reactions' })).toBe(
      '/fit/abc123',
    );
  });

  it('refuses a path carrying a route group', () => {
    // `(tabs)` organises files and never appears in a URL. Two server
    // targets carried it, both tapped through to nothing, and the app
    // showed a developer error screen. Fixed at the source, and
    // refused here too: notifications already delivered still carry
    // the old target and no server fix reaches them.
    expect(routeFor({ named: '/(tabs)/wardrobe', kind: 'wardrobe_sorted' })).toBe(
      '/wardrobe',
    );
  });

  it('refuses a path trying to climb out', () => {
    expect(routeFor({ named: '/../secrets', kind: 'wardrobe_sorted' })).toBe(
      '/wardrobe',
    );
  });

  it('refuses something that is not a path at all', () => {
    expect(routeFor({ named: 'https://example.com', kind: 'studio_ready' })).toBe(
      '/studio',
    );
  });

  it('falls back to the kind when nothing was named', () => {
    expect(routeFor({ kind: 'studio_ready' })).toBe('/studio');
    expect(routeFor({ named: null, kind: 'stylist_ready' })).toBe('/stylist');
  });

  it('ignores a named path that is only whitespace', () => {
    expect(routeFor({ named: '   ', kind: 'wardrobe_sorted' })).toBe('/wardrobe');
  });

  it('always produces somewhere to go', () => {
    // A tap that does nothing is indistinguishable from a tap that
    // was not registered, which is the worst thing a notification
    // can do.
    expect(routeFor({})).toBe(NOTIFICATION_FALLBACK);
    expect(routeFor({ named: null, kind: 'something-new' })).toBe(
      NOTIFICATION_FALLBACK,
    );
  });

  it('routes a finished studio job to the studio', () => {
    expect(routeFor({ kind: 'studio_ready' })).toBe('/studio');
  });

  it('never maps a kind to a path with a group in it', () => {
    for (const path of Object.values(NOTIFICATION_ROUTES)) {
      expect(path.startsWith('/')).toBe(true);
      expect(path).not.toContain('(');
    }
    expect(NOTIFICATION_FALLBACK).not.toContain('(');
  });
});

describe('every kind the server can send has somewhere to go', () => {
  // The server's two lists, copied here deliberately rather than
  // imported: they live in Python, and the point of this test is to
  // fail when one of them grows a kind the app has never heard of.
  // `services/api/tests/test_notification_targets.py` is the other
  // half and checks these against the routes that exist.
  const INBOX_KINDS = ['wardrobe_sorted', 'stylist_ready', 'fit_reactions'];
  const PUSH_KINDS = ['fit_saved', 'new_follower', 'studio_ready', 'message'];

  it('names a home for each one rather than dropping it on the inbox', () => {
    // The fallback is for a kind this build predates, not for one it
    // knows about. A banner saying a studio shot is ready that opens
    // the inbox is a tap that did not do what it said.
    for (const kind of [...INBOX_KINDS, ...PUSH_KINDS]) {
      expect(NOTIFICATION_ROUTES[kind]).toBeDefined();
      expect(routeFor({ kind })).not.toBe(NOTIFICATION_FALLBACK);
    }
  });

  it('still prefers the path the server named', () => {
    // The kind map is the fallback. A saved-fit notice knows which
    // fit, and must open that one rather than the shelf.
    expect(routeFor({ named: '/fit/abc123', kind: 'fit_saved' })).toBe(
      '/fit/abc123',
    );
    expect(routeFor({ named: '/member/abc123', kind: 'new_follower' })).toBe(
      '/member/abc123',
    );
  });
});
