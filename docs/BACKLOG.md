# Backlog

Everything requested in this project that is **not yet visible in the running
app**, audited against the full conversation on 2026-10-28.

The honest pattern behind most of this: several things were built as
infrastructure and never connected to a screen. Semantic colours exist as
tokens that nothing uses. Skeletons exist as a component that nothing renders.
The stylist works against the live API but the Stylist tab shows an empty
state. Tests pass on all of it, which is exactly why it went unnoticed, and is
the reason this list is ordered by *what you can see* rather than by what is
architecturally interesting.

Checked off only when the change is visible in the app, not when the code
lands.

---

## A. Built but not wired

The highest-value items, because the work is mostly done and the gap is a
connection.

- [~] **A1. Stylist tab is a dead end.** *Composer done; the run is still
      blocked.* The tab now opens with wardrobe readiness, a request field,
      prompt chips that fill the field rather than commit to a phrasing, dress
      codes, and a thinking state. Tapping "Style me" reports that sign-in is
      needed, which is the real reason, rather than spinning or inventing an
      outfit locally. Completes when A4 and A5 land.
- [x] **A2. Semantic colours are unused.** Now used in four places:
      availability badges on wardrobe cells, the availability chips in the
      garment sheet, owned/not-owned on the look detail, and stylist
      readiness. Colour is never the only signal — each carries a dot or a
      word too, per WCAG 1.4.1. `toneColor()` in the theme resolves a
      *meaning* to a colour, so no screen names a semantic hex. `borderStrong`
      now bounds every outlined control and text input, which is what WCAG
      1.4.11 asks for.
- [x] **A3. Skeletons are unrendered.** `SkeletonText` and `useDelayedVisible`
      now drive the stylist's thinking state, held back 400ms so a fast result
      never flashes a placeholder. `SkeletonGrid` stays unused until a grid
      loads over the network (A5).
- [x] **A4. No sign-in screen.** `app/sign-in.tsx` leads with Continue with
      Google and keeps an email route secondary, because offering exactly one
      identity provider locks out anyone without that account. No guest mode:
      the app is a personal wardrobe, so signed-out would be an empty shell.
      Profile now opens its Account section with the signed-in state and a
      Sign in / Sign out row. Cancelling the browser is treated as a decision,
      not an error.
- [~] **A5. Wardrobe is local-only.** *Server side proven; mobile still to
      wire.* The blocker was not auth, it was that no storage backend existed:
      the stub stored nothing and GCS refuses for want of a credential, so no
      photograph could reach the server at all. `app/storage/local.py` is the
      missing backend, refused outside the local environment by enforcement.
      The full path now runs against real Postgres, the real model and the
      real parser. What remains is the mobile store calling it.

## B. Requested features not yet present

- [x] **B1. "Ask the stylist about this look" loses the look.** The look id
      now travels as a route param. The Stylist opens with an "Asking about"
      card naming the look and how many of its pieces are already owned, and
      the request field is pre-filled. Read into initial state rather than
      synced from an effect, which would render empty and then flash.
- [ ] **B2. Favourites do not reach the model.** Hearting a garment is stored
      locally. The request was that favourites inform styling; nothing sends
      them, and the stylist has no idea what the user loves.
- [~] **B3. Background removal is not visible.** *Works; not yet on a phone.*
      A real photograph now comes back as a cut-out on the warm ground with
      its contact shadow. Three bugs had to go first: providers built without
      an AIRunRecorder, the media store never wired, and the parser adapter
      written against attribute names the installed package does not have.
- [~] **B4. Auto-categorisation is not visible.** *Works; not yet on a
      phone.* The linen shirt returns slot `tops`, category `shirt`, beige,
      plain, linen at 0.95. It had been failing with "did not return JSON"
      because the 512-token cap covers reasoning tokens and the model spent
      all of them before emitting anything.
- [ ] **B5. No search in Discover.** Browsing is by category chip only. A
      fashion app with a grid and no search is hard to use once there is more
      than a screenful.
- [ ] **B6. Trending is per-device only.** Correctly labelled "Popular with
      you" rather than "Trending", which was deliberate. It stays a local
      ranking until interactions reach the server, so the honest label stands
      and this is the work to make the real thing possible.

## C. Visual polish still owed

- [x] **C1. Animations are on two screens.** Now on the look detail (piece
      rows stagger in, actions take press motion), Profile (rows compress at
      0.99 rather than the tile's 0.975, because a visible scale on something
      full-width reads as the whole screen moving) and the Stylist composer.
      Community is still a placeholder by design.
- [ ] **C2. Bodoni Moda renders at the wrong optical size.** The bundled
      static instances are cut for 11pt text and are used at 30px and 96px. A
      didone at display size needs the fine hairlines of its display cut; the
      variable font exists and React Native 0.88 supports
      `fontVariationSettings`.
- [ ] **C3. Wardrobe placeholders should be ThumbHash, not BlurHash.**
      BlurHash is RGB-only and cannot represent alpha, so a cut-out garment's
      transparent region renders as a muddy averaged colour. ThumbHash
      supports alpha at the same 28-character cost and `expo-image` already
      supports it.
- [ ] **C4. Empty states are thin.** Several screens state the empty fact with
      no route out. The premium convention is one line of fact plus one action.
- [ ] **C5. No pull-to-refresh anywhere.** Expected on every scrollable list
      in a mobile app.

## D. Blocked or needs a decision

- [x] **D1. Keycloak has never imported this realm.** It has now. The realm
      imports, discovery serves, and the `${GOOGLE_CLIENT_ID}` substitution
      works: the Google provider carries the real client id with
      `trustEmail` still false.
- [ ] **D2. Expo Go redirect URI is not registered.** The realm lists
      `luxish://callback` and ports 8081. Expo Go produces
      `exp://<host>/--/callback`, and the host changes every time the tunnel
      restarts. Needs either a dev-only wildcard in the dev realm or a
      development build, which is the cleaner answer.
- [x] **D3. Two Postgres-marked tests have never run.** Both pass now, and
      they earned their keep immediately: a self-referencing foreign key
      generated a 64-character constraint name against PostgreSQL's 63-char
      limit, which SQLite does not enforce, so 719 tests passed while
      `alembic upgrade head` failed on the first real database it met. They
      also shared a database — `test_jobs` drops the tables but leaves
      `alembic_version`, making the migration test's `upgrade head` a no-op.
      Separate database now, and the migration test resets its own schema.
- [ ] **D4. Community is a placeholder.** Correctly labelled as not open yet.
      Listed so it is not mistaken for an oversight.

---

## Done

Moved here as items complete, newest first.

### 2026-10-28

- **D1** Keycloak imports the realm; Google sign-in configured and verified.
- **D3** both Postgres tests pass, having found a real 63-char identifier bug.
- **A5/B3/B4** *partial*: the media pipeline runs end to end on the server.
- **A4** sign-in screen, Google first, with the signed-in state on Profile.
- **B1** the stylist now knows which look you asked about.
- **A2** semantic colours now carry meaning on four screens, never by colour alone.
- **A3** skeletons render for the first time, in the stylist's thinking state.
- **C1** animations extended to the look detail, Profile and Stylist.
- **A1** *partial*: the Stylist composer exists; the run still needs sign-in.
