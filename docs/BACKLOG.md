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

- [ ] **A1. Stylist tab is a dead end.** The loop runs against the live Meta
      API and produces real outfits, verified with five paid runs. The tab
      shows "No outfits yet" and has no way to ask for one. Needs a request
      composer, a run view with progress, and the outfit result.
- [ ] **A2. Semantic colours are unused.** `success`, `warning`, `danger` and
      `borderStrong` are defined and contrast-tested; no screen references
      them. Availability states, failed uploads and low-confidence
      categorisation should all read through them.
- [ ] **A3. Skeletons are unrendered.** `SkeletonGrid`, `SkeletonText` and
      `useDelayedVisible` exist with tests. Nothing imports them. They become
      real as soon as any screen loads over the network, which A5 introduces.
- [ ] **A4. No sign-in screen.** The PKCE flow, token storage and refresh are
      implemented. There is no UI to trigger them, so the app has never signed
      anybody in. Needs a sign-in screen with "Continue with Google", and a
      signed-out state on Profile.
- [ ] **A5. Wardrobe is local-only.** Photos save to on-device storage and
      never reach the API, so auto-categorisation and background removal are
      unreachable from the app despite both being implemented and tested
      server-side.

## B. Requested features not yet present

- [ ] **B1. "Ask the stylist about this look" loses the look.** The button
      navigates to the Stylist tab and drops the context, so the user has to
      describe the outfit they were just looking at. It should carry the look
      in and show it as the subject of the question.
- [ ] **B2. Favourites do not reach the model.** Hearting a garment is stored
      locally. The request was that favourites inform styling; nothing sends
      them, and the stylist has no idea what the user loves.
- [ ] **B3. Background removal is not visible.** The cut-out plus contact
      shadow is implemented and tested server-side. No wardrobe photo in the
      app has ever been through it.
- [ ] **B4. Auto-categorisation is not visible.** Same: the classifier sorts
      into the five slots, with confidence recorded, and nothing in the app
      calls it. Garments currently land in whatever slot the local heuristic
      guesses.
- [ ] **B5. No search in Discover.** Browsing is by category chip only. A
      fashion app with a grid and no search is hard to use once there is more
      than a screenful.
- [ ] **B6. Trending is per-device only.** Correctly labelled "Popular with
      you" rather than "Trending", which was deliberate. It stays a local
      ranking until interactions reach the server, so the honest label stands
      and this is the work to make the real thing possible.

## C. Visual polish still owed

- [ ] **C1. Animations are on two screens.** Discover and Wardrobe have the
      entrance stagger and press motion. Stylist, Community, Profile and the
      look detail screen have none, so the app feels inconsistent as you move
      between tabs.
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

- [ ] **D1. Keycloak has never imported this realm.** Docker could not start
      containers on this machine for the whole session. The `${GOOGLE_CLIENT_ID}`
      substitution in realm import is therefore unproven here, and is the first
      thing to check once the stack runs.
- [ ] **D2. Expo Go redirect URI is not registered.** The realm lists
      `luxish://callback` and ports 8081. Expo Go produces
      `exp://<host>/--/callback`, and the host changes every time the tunnel
      restarts. Needs either a dev-only wildcard in the dev realm or a
      development build, which is the cleaner answer.
- [ ] **D3. Two Postgres-marked tests have never run.** They cover
      `SKIP LOCKED` and the partial unique index, neither of which SQLite can
      exercise. Blocked on the same Docker issue.
- [ ] **D4. Community is a placeholder.** Correctly labelled as not open yet.
      Listed so it is not mistaken for an oversight.

---

## Done

Moved here as items complete, newest first.
