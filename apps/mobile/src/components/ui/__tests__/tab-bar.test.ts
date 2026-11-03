import {
  DESTINATIONS,
  currentHref,
  selectedHref,
  showsTabBar,
  tabBarShowing,
  tabFromState,
} from '@/components/ui/tab-bar';

describe('showsTabBar', () => {
  it('stays on a pin, which is the whole point of moving it', () => {
    // The bar used to be drawn inside the tab group, so opening a pin
    // covered it and getting to another tab meant going back first.
    expect(showsTabBar('/fit/abc123')).toBe(true);
  });

  it('stays on every pushed screen that does not own its bottom', () => {
    for (const path of ['/closet', '/stylist', '/insights', '/saved', '/tag/linen']) {
      expect(showsTabBar(path)).toBe(true);
    }
  });

  it('stands down where a screen draws its own bottom controls', () => {
    // Two bars at the bottom of one screen is two places to look for
    // the way out, and on an editor the floating one sits over the
    // controls somebody is using.
    expect(showsTabBar('/collage')).toBe(false);
    expect(showsTabBar('/compose')).toBe(false);
  });

  it('stands down in a message thread', () => {
    // A composer pinned to the bottom edge with quick replies above
    // it. The bar landed on both.
    expect(showsTabBar('/messages')).toBe(false);
    expect(showsTabBar('/messages/abc123')).toBe(false);
    expect(showsTabBar('/messages/new')).toBe(false);
  });

  it('stays off the way in', () => {
    expect(showsTabBar('/welcome')).toBe(false);
    expect(showsTabBar('/sign-in')).toBe(false);
  });

  it('matches a whole segment, not a prefix of a word', () => {
    // `/composer` is not `/compose`, and a bar that vanished on a
    // route nobody thought about would be hard to explain.
    expect(showsTabBar('/composer')).toBe(true);
    expect(showsTabBar('/compose/anything')).toBe(false);
  });
});

describe('selectedHref', () => {
  it('marks the tab you are actually on', () => {
    expect(selectedHref('/')).toBe('/');
    expect(selectedHref('/search')).toBe('/search');
    expect(selectedHref('/profile')).toBe('/profile');
  });

  it('marks nothing on a pushed screen', () => {
    // The path alone cannot say. `currentHref` asks the navigator.
    expect(selectedHref('/fit/abc123')).toBeNull();
    expect(selectedHref('/closet')).toBeNull();
  });
});

/** A navigator tree shaped the way the router builds one. */
function tree(focusedTab: string, pushed?: string) {
  const tabs = {
    index: DESTINATIONS.findIndex((d) => d.name === focusedTab),
    routes: DESTINATIONS.map((d) => ({ name: d.name })),
  };
  return {
    index: pushed ? 1 : 0,
    routes: pushed
      ? [{ name: '(tabs)', state: tabs }, { name: pushed }]
      : [{ name: '(tabs)', state: tabs }],
  };
}

describe('tabFromState', () => {
  it('reads the focused tab out of the navigator', () => {
    expect(tabFromState(tree('search'))).toBe('/search');
    expect(tabFromState(tree('profile'))).toBe('/profile');
  });

  it('still reads it with a screen pushed over the tabs', () => {
    // The whole point: a pin sits over Discover, and Discover is
    // still the section somebody is in.
    expect(tabFromState(tree('index', 'fit/[id]'))).toBe('/');
    expect(tabFromState(tree('search', 'fit/[id]'))).toBe('/search');
  });

  it('answers null rather than guessing on a shape it does not know', () => {
    expect(tabFromState(undefined)).toBeNull();
    expect(tabFromState({})).toBeNull();
    expect(tabFromState({ routes: [{ name: 'nothing' }] })).toBeNull();
  });

  it('does not hang on a tree that points at itself', () => {
    const loop: Record<string, unknown> = { routes: [] };
    loop.state = loop;
    expect(tabFromState(loop)).toBeNull();
  });
});

describe('currentHref', () => {
  it('prefers the path when it names a tab outright', () => {
    expect(currentHref('/search', '/')).toBe('/search');
  });

  it('falls back to the navigator on a pushed screen', () => {
    expect(currentHref('/fit/abc', '/')).toBe('/');
  });

  it('lights nothing when neither knows', () => {
    // A fit no longer reaches this: it belongs to Discover wherever
    // it was opened from. Something genuinely unplaceable still does.
    expect(currentHref('/tag/linen', null)).toBeNull();
  });
});

describe('DESTINATIONS', () => {
  it('is the five the bar was designed around', () => {
    // Five chips fit on one line at a readable size; a sixth is a
    // layout change, not a list change.
    expect(DESTINATIONS).toHaveLength(5);
  });

  it('gives every chip a name for a screen reader', () => {
    // The bar is icons only, so the label is the only thing anybody
    // not looking at it has.
    for (const destination of DESTINATIONS) {
      expect(destination.label.length).toBeGreaterThan(0);
    }
  });

  it('points every chip at a distinct route', () => {
    const hrefs = DESTINATIONS.map((destination) => destination.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});

describe('tabBarShowing', () => {
  it('stands down for a keyboard on a screen somebody can back out of', () => {
    // The general rule. A deny-list only knows the screens somebody
    // remembered, and every screen with a text field is one where
    // the bar can land on what is being typed into.
    for (const path of ['/closet', '/fit/abc', '/tag/linen']) {
      expect(tabBarShowing({ pathname: path, keyboardUp: true })).toBe(false);
    }
  });

  it('keeps the bar on a tab root even then, because it is the only way out', () => {
    // The stylist moved onto the wardrobe page, which made a tab
    // root contain a text field. Tapping it raised the keyboard,
    // this rule removed the bar, and a tab root has no chevron - so
    // the page had no navigation on it at all, and the only way on
    // was to guess that dismissing the keyboard would bring it back.
    for (const path of ['/', '/search', '/wardrobe', '/studio', '/profile']) {
      expect(tabBarShowing({ pathname: path, keyboardUp: true })).toBe(true);
    }
  });

  it('still never shows one where the screen owns its bottom edge', () => {
    // That rule outranks both: a message thread is a composer
    // pinned to the bottom, and it is a pushed screen with a way
    // back of its own.
    expect(
      tabBarShowing({ pathname: '/messages/abc', keyboardUp: true }),
    ).toBe(false);
  });

  it('comes back when the keyboard goes down', () => {
    expect(tabBarShowing({ pathname: '/', keyboardUp: false })).toBe(true);
  });

  it('still respects a screen that owns its bottom edge', () => {
    // Keyboard down, composer still there.
    expect(
      tabBarShowing({ pathname: '/messages/abc', keyboardUp: false }),
    ).toBe(false);
  });
});

describe('a pin belongs to Discover wherever it was opened from', () => {
  // The bar was reporting the route taken rather than where somebody
  // is. Opening your own upload from your profile lit the Profile
  // chip, which says a pin is a profile page; opening the same pin
  // from the board lit Discover. One page, two answers.
  it('lights Discover for a pin pushed over the profile tab', () => {
    expect(currentHref('/fit/abc123', '/profile')).toBe('/');
  });

  it('lights Discover for one pushed over search', () => {
    expect(currentHref('/fit/abc123', '/search')).toBe('/');
  });

  it('lights Discover even when the navigator knows nothing', () => {
    expect(currentHref('/fit/abc123', null)).toBe('/');
  });

  it('still lets a real tab in the path win', () => {
    expect(currentHref('/profile', '/')).toBe('/profile');
  });

  it('leaves every other pushed screen to the navigator', () => {
    // A closet opened from the wardrobe tab is a wardrobe thing; a
    // member page opened from search is a search thing. Only the fit
    // is the same page from everywhere.
    expect(currentHref('/closet', '/wardrobe')).toBe('/wardrobe');
    expect(currentHref('/member/abc', '/search')).toBe('/search');
    expect(currentHref('/saved', '/profile')).toBe('/profile');
  });

  it('is not fooled by a word that merely starts the same', () => {
    expect(currentHref('/fitting-room', '/profile')).toBe('/profile');
  });
});

describe('the bar yields while somebody is looking at one thing', () => {
  // the behaviour people expect, and the reason the route alone is the
  // wrong unit: a fit's page opens as one photograph filling the
  // screen, where five chips across the bottom sit on it, and
  // becomes a grid of other fits once you scroll past it, where the
  // chips are how you leave. One route, two postures.
  it('stands down while the screen is immersed', () => {
    expect(
      tabBarShowing({ pathname: '/fit/abc', keyboardUp: false, immersed: true }),
    ).toBe(false);
  });

  it('comes back once the screen says browsing has begun', () => {
    expect(
      tabBarShowing({ pathname: '/fit/abc', keyboardUp: false, immersed: false }),
    ).toBe(true);
  });

  it('treats a screen that reports nothing as browsing', () => {
    // Every list, form and tool in the app. They want the bar from
    // the first pixel and none of them will ever call the hook.
    expect(tabBarShowing({ pathname: '/', keyboardUp: false })).toBe(true);
    expect(tabBarShowing({ pathname: '/wardrobe', keyboardUp: false })).toBe(true);
  });

  it('still stands down for a keyboard whatever the posture', () => {
    // The keyboard rule is the general one and outranks this.
    expect(
      tabBarShowing({ pathname: '/fit/abc', keyboardUp: true, immersed: false }),
    ).toBe(false);
  });

  it('cannot be talked into appearing on a screen that owns its bottom', () => {
    // A message composer does not become safe to cover because
    // nothing reported a posture.
    expect(
      tabBarShowing({ pathname: '/messages/abc', keyboardUp: false, immersed: false }),
    ).toBe(false);
  });
});

describe('account screens belong to the profile tab', () => {
  // They are pushed onto the root stack rather than into the profile
  // tab's own, so the navigator reports whichever tab happened to be
  // focused underneath - and opening settings lit Discover.
  it('lights Profile for settings however it was reached', () => {
    expect(currentHref('/settings', '/')).toBe('/profile');
    expect(currentHref('/settings', null)).toBe('/profile');
  });

  it('does the same for the screens under it', () => {
    for (const path of [
      '/notification-settings',
      '/profile-edit',
      '/subscription',
      '/insights',
      '/saved',
    ]) {
      expect(currentHref(path, '/')).toBe('/profile');
    }
  });

  it('still leaves a shared screen to the navigator', () => {
    // A member page is reached from search, from a comment, from a
    // follower list. Which tab it belongs to really is a fact about
    // the route taken.
    expect(currentHref('/member/abc', '/search')).toBe('/search');
    expect(currentHref('/closet', '/wardrobe')).toBe('/wardrobe');
  });
});
