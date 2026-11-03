# Backlog

Everything requested in this project that is **not yet visible in the running
app**, audited against the full conversation on 2026-10-28 and worked through
on 2026-10-29.

**Section J is open as of 2026-10-31**, and is the community platform
brief. Everything above it was closed on 2026-10-29: the Done section
carries what each item actually turned out to be, including the two cases
where the measurement contradicted the plan recorded here.

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

- [x] **A1. Stylist tab is a dead end.** It runs. Tapping "Style me" starts a real run and
      renders a real outfit, each piece marked as yours or suggested, with the
      stylist's own reasoning and any slot it could not fill.

      Three things were in the way, and only the first was expected:

      * **the run was a stub**, reporting that sign-in was needed long after
        sign-in worked;
      * **consent could be read but never granted.** The provider registry
        refuses to route anything without `ai_processing` consent, and no
        endpoint existed to give it, so the stylist reported that the styling
        service was unavailable while it was working perfectly and correctly
        declining. A gate with no handle is a feature nobody can use. There
        are now `GET /v1/consents` and `PUT /v1/consents/{kind}`, asked for at
        the point of use rather than in a wall of toggles at sign-up, and
        withdrawable from Profile in one tap by the same endpoint;
      * **the token cap truncated the answer.** At `max_completion_tokens`
        1200 the tool-calling turns completed normally (181, 329, 722 tokens)
        and the final turn stopped at exactly 1200 with `finish_reason:
        length`, so the run reported `model_output_unusable`. The cap covers
        reasoning tokens, which the model spends first. Raised to 4096 — the
        same mistake, at 512, is what made categorisation claim it "did not
        return JSON".

      Two client bugs fell out of measuring rather than assuming: the terminal
      state is `completed`, not `succeeded`, so the app would have polled a
      finished run until it gave up; and a real run against a 28-garment
      wardrobe took **155 seconds**, against a 60-second poll budget. Both are
      now taken from the server's own vocabulary and a measured run.
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
- [x] **A5. Wardrobe is local-only.** The blocker turned out not to be auth
      but that no storage backend existed at all: the stub stored nothing and
      GCS refuses for want of a credential. `app/storage/local.py` is the
      missing backend, refused outside the local environment by enforcement.
      `features/wardrobe/sync.ts` is the mobile half: authorise, PUT, create,
      poll. Local-first rather than local-only, so a photograph is never lost
      waiting for a network, and `serverId` being absent is what marks one as
      unsent.

## B. Requested features not yet present

- [x] **B1. "Ask the stylist about this look" loses the look.** The look id
      now travels as a route param. The Stylist opens with an "Asking about"
      card naming the look and how many of its pieces are already owned, and
      the request field is pre-filled. Read into initial state rather than
      synced from an effect, which would render empty and then flash.
- [x] **B2. Favourites do not reach the model.** Both halves were missing,
      not one. The heart wrote only to the device, *and* `is_favourite` was
      never read by the stylist. The heart now also calls the server for any
      garment that has a server id, and `candidate_garments` orders favourites
      first. The ordering is the part that matters: that list is capped, so in
      a wardrobe larger than the cap an age-only order silently hid the
      clothes someone said they love behind whatever they added first.
      `describe()` also emits "favourite" and "loved", so "use my favourite
      jacket" is a constraint rather than a phrase that gets ignored. The cap
      test fails without the ordering change.
- [x] **B3. Background removal is not visible.** *Visible on a phone.*
      A real photograph now comes back as a cut-out on the warm ground with
      its contact shadow. Three bugs had to go first: providers built without
      an AIRunRecorder, the media store never wired, and the parser adapter
      written against attribute names the installed package does not have.
- [x] **B4. Auto-categorisation is not visible.** *Visible on a phone.* The linen shirt returns slot `tops`, category `shirt`, beige,
      plain, linen at 0.95. It had been failing with "did not return JSON"
      because the 512-token cap covers reasoning tokens and the model spent
      all of them before emitting anything.
- [x] **B5. No search in Discover.** One `SearchField`, used by Discover and
      the Wardrobe. Filters as you type, because both lists are in memory and
      making someone press return would add a step that buys nothing. Discover
      searches titles, subtitles and cues, so "sneakers" finds Streetwear even
      though the word is not in its name; the Wardrobe searches the name plus
      what the model read off the photo, so "denim" finds the jeans someone
      called "work trousers". Every term must match, in any order, and
      substrings count because garment words are full of compounds.
- [x] **B6. Trending is per-device only.** Interactions now reach the server
      and are aggregated across people, so the word is available for the first
      time. Three rules decide whether it may be used, and each is a way the
      feature could otherwise lie:

      * **more than one person.** A look must have been touched by at least
        `MIN_DISTINCT_USERS` (3) before it appears, and each person counts
        once per kind, so one enthusiast viewing something forty times is an
        afternoon rather than a trend;
      * **recent.** Nothing outside a fortnight counts at all, and inside it
        events decay with a week's half-life;
      * **intent over attention.** Saving outweighs viewing, on the client's
        own weights, so the local and server rankings mean the same thing.

      An empty list is a real answer meaning nothing has cleared the
      threshold, and the shelf hides rather than falling back to local data
      while keeping the global label. `occurred_at` is device time, so a phone
      that was offline for a day does not post its backlog as a spike;
      `aesthetics` is stored on the event, so recategorising a look does not
      rewrite last week. Re-uploading is expected and deduplicated by
      constraint, because a flaky connection must not read as enthusiasm.
      Verified end to end with three real accounts: the shared look trended,
      the one-person look was withheld.

- [x] **B7. Saved pins have no home of their own.** They are viewable, but
      only as the entire contents of the **Community** tab, and that is two
      problems wearing one screen. A tab called Community that shows your
      private collection is mislabelled; and the collection itself has nowhere
      to grow into what a saved pin should carry — the note you kept it for,
      the occasion you kept it *for*, which pieces you already own, what order
      you want them in.

      Also device-only. `saved.ts` writes to kv-store and says so, with the
      migration deliberately deferred until there was a session to migrate
      into. There is one now, so the honest statement is no longer "no
      authenticated identity yet": a reinstall still loses everything someone
      kept, and a second device starts empty.

      What is owed: saved pins as their own destination, reachable without
      going through a tab that means something else; persisted server-side
      against the account; and the migration from kv-store on first sign-in,
      written so nothing silently disappears at the moment it runs. The keys
      and stored shape were chosen for exactly this, so the migration is the
      easy half.

- [x] **B8. There are no notifications, anywhere.** Not a screen, not a
      model, not a table, not a permission request. The app currently cannot
      tell anyone that anything happened.

      Two separate things are missing and they should not be conflated:

      * **An inbox.** A place that lists what happened while you were away —
        someone reacted to a look you kept, a photo you uploaded finished
        being sorted, a stylist run completed. This is the half that matters
        first, because the events already exist: uploads finish
        asynchronously, trending moves, community reactions accumulate. Today
        all of that is only discoverable by going and looking.
      * **Push.** Delivery to a device that is not open. Needs
        `expo-notifications`, a token per device, a permission request made at
        a moment that earns it rather than on first launch, and a per-kind
        preference — the same honesty rule as consents: whatever can be
        switched on must be switchable off in the place it is reported.

      Neither should invent activity. An empty inbox is a real answer, and
      "someone saved your look" needs the same `MIN_DISTINCT_USERS` honesty
      that trending already enforces, or the first notification most people
      receive will be about an audience of one.

## C. Visual polish still owed

- [x] **C1. Animations are on two screens.** Now on the look detail (piece
      rows stagger in, actions take press motion), Profile (rows compress at
      0.99 rather than the tile's 0.975, because a visible scale on something
      full-width reads as the whole screen moving) and the Stylist composer.
      Community is still a placeholder by design.
- [x] **C2. Bodoni Moda renders at the wrong optical size.** `BodoniModa[opsz,wght].ttf` is now
      bundled from the Google Fonts repository with its OFL text, replacing
      the two static instances and the package that shipped them. The file
      exposes `wght` 400-900 and `opsz` 6-96, and its `opsz` **default is 11**
      — which is exactly the problem: the statics it replaces carried no
      `fvar` table at all, so they were that 11pt cut and nothing else, set at
      44px for a screen title. `displayType(size)` now passes the pixel size
      straight to the `opsz` axis at all 18 call sites, so a heading is drawn
      with the cut it would have been given in metal. Weight travels as the
      `wght` axis rather than `fontWeight`, which with a variable font invites
      the platform to synthesise a bold instead of interpolating one. One
      162KB variable file against two statics is roughly cost-neutral.
- [x] **C3. Wardrobe placeholders should be ThumbHash, not BlurHash.** User
      garments now carry a ThumbHash, generated on the device with
      `Image.generateThumbhashAsync` when a picture is adopted, and the grid
      prefers it. The bundled style covers deliberately keep BlurHash: they
      are opaque photographs with no alpha to lose, so converting them would
      buy nothing. Generation returns null rather than throwing, since a
      missing placeholder is a smaller problem than a wardrobe that will not
      load.
- [x] **C4. Empty states are thin.** Discover and the Wardrobe now use the
      existing `EmptyState`, which already took an action — the gap was that
      nothing passed one. The action depends on *why* the list is empty: a
      failed search offers to clear the filters, an empty wardrobe offers the
      camera, and an empty favourites tab explains the heart.
- [x] **C5. No pull-to-refresh anywhere.** On the Wardrobe, which is the one
      list backed by the server: it pulls garments the device has never seen,
      which is how outfit-detected pieces arrive. Deliberately *not* added to
      Discover or the look detail — both render bundled data, and a refresh
      control that refetches nothing is a control that lies. They get one when
      B6 gives them something to fetch.

## F. The elite UI brief

Supplied on 2026-10-29. Recorded in full rather than summarised, because three
parts of it collide with decisions already recorded in ADR-019, and that
collision should be resolved on purpose rather than discovered later.

- [x] **F1. Typography: display pairings and radical weight contrast.**
      Import high-contrast families from Google Fonts and pair them with no
      medium weights in between: an ultra-light 100/200 heading directly
      against a thick 800/900 uppercase sub-label.

      * Editorial headings: Cormorant Garamond, Playfair Display, or Prata.
      * Minimalist labels: Space Grotesk, Syncopate, or Syne.

      **Conflicts with ADR-019, and the brief wins unless you say otherwise.**
      That ADR records a decision to keep *body* copy on the system face, on
      the grounds that a custom UI font is the fastest way to make a native
      app feel like a website wearing a costume. The brief says never to use
      a system font. Both cannot hold. The narrow reading that satisfies both
      is: custom faces for display and labels, system face for running body
      copy, which is roughly where the app already is now that Bodoni Moda is
      variable and the body scale has been fixed. If you want it everywhere,
      say so and ADR-019 gets amended rather than quietly broken.

      Two smaller notes. The brief's "weight 100/200" is not available in
      every family named: Playfair Display's variable axis starts at 400, so
      an ultra-light heading needs Cormorant Garamond or a different face.
      And the app already bundles a variable didone with a real optical-size
      axis, which is a stronger version of the same idea than swapping in
      another static serif.

- [x] **F2. Motion: Moti for layout, Lottie for feedback.**
      `moti` is declarative animation over Reanimated, which is already a
      dependency, so this is additive rather than a new engine.
      `lottie-react-native` ships in the Expo SDK, so it runs in Expo Go
      without a development build.

      The thing to hold on to while doing it: ADR-019 records that skeletons
      deliberately do not shimmer, because WCAG 2.2.2's loading-animation
      exemption only applies when the animation is the only content on the
      page. A Lottie loader is subject to the same rule. Micro-rewards on a
      tap are not, because they answer an action.

- [x] **F3. Layout: 8-point grid, 60/30/10 colour.**
      The spacing scale is already a 4-point grid, which contains the 8-point
      one; this is a question of using the larger steps rather than changing
      the tokens. The 60/30/10 split is compatible with the existing palette:
      warm paper at 60, the element surface at 30, burgundy at 10.

- [x] **F4. Reference material: the sources named cannot all be read.**
      Recorded so nobody spends an afternoon rediscovering it. ADR-019
      already found that **mobbin.com returns 403 to any non-browser client**,
      along with three of the four galleries in the original brief being
      unusable. 21st.dev and the Figma Community kit are both fetchable and
      worth mining; Mobbin needs a person with a browser to pull the flows
      out by hand.

      The brief also mentions "global tailwind configurations". This app does
      not use Tailwind or NativeWind: it uses `StyleSheet` over the tokens in
      `constants/theme.ts`. The guidance translates, the file does not exist.

## G. Personalisation, and the cost mechanism behind it

Requested 2026-10-29. One feature with a cost model attached, which is the
part that makes it tractable: generating fresh inspiration per user per week
is a per-user model bill, and the way out is that users with similar wardrobes
and similar taste can be served the same generated inspiration.

Recorded as six items because they ship in order and each is useful alone.
The whole of G is **planned**; none of it is built.

- [x] **G1. Taste questions at sign-up.** A short multiple-choice set, asked
      once, that gives a new account a starting taste profile before it has
      any interaction history at all. Without it the personalised shelf has
      nothing to personalise from on day one, which is the only day it most
      needs to be good.

      Constraints this has to inherit, because they are already settled
      elsewhere in this service:

      * **Asked, never inferred**, and every question skippable. The avatar's
        appearance vocabulary set that precedent and the reasoning carries
        over exactly: a taste profile derived from somebody's clothes rather
        than from their answers is an inference about a person.
      * **Stored as `preferences`**, whose own rule is that a stated
        preference beats an inference. That is the table that makes "asked"
        structural rather than a convention.
      * Answering must not be a wall between sign-up and the product. Browsing
        already works without an account; this must not be the thing that
        stops it.

- [x] **G2. A taste profile from wardrobe plus interaction.** Combine what
      somebody owns (`garments`: slot, category, colour, formality) with what
      they reach for (`look_interactions`, already weighted and already
      decaying). Both signals exist and neither is read today.

      The honest bit: these two disagree often and the disagreement is the
      signal. Somebody whose wardrobe is entirely workwear and who only ever
      taps festival looks is telling you two different true things, and a
      profile that averages them serves neither. Decide and record which one
      leads for which shelf before building it.

- [x] **G3. Taste cohorts — the thing that makes G4 affordable.** Group users
      by wardrobe composition and taste profile, so one generated set of
      inspiration serves everybody in a cohort rather than one person.

      **The privacy constraint is the whole design, not a caveat.** The
      repository rule is that a wardrobe is private and a garment is
      re-validated against its owner before it is rendered. A cohort may
      therefore be built from *aggregate type counts* — "owns tailoring, owns
      denim, no formalwear" — and never from garments themselves. No user's
      garment, photograph, cut-out or name may reach another user through a
      cohort, and nothing generated for a cohort may be conditioned on one
      member's specific items. Get this wrong and the feature leaks wardrobes
      between strangers, silently.

      A cohort also needs a floor on membership for the same reason trending
      has `MIN_DISTINCT_USERS`: a "cohort" of one is just that person's
      wardrobe with a shared label on it.

- [x] **G4. "How to wear what you own", personalised and refreshed twice a
      week.** Today that shelf is the `formula` lens and it is identical for
      everybody. It should be built from the viewer's own profile and cohort,
      and regenerated on a schedule so the shelf is different on Thursday from
      how it was on Monday.

      Scheduled work already has a home — Celery beat runs the sweeper — so
      this is a periodic task, not a new mechanism. What it needs that does
      not exist: somewhere to store a generated set per cohort with a validity
      window, and a rule for what a user sees when their cohort's set has not
      been generated yet. A spinner twice a week is not that rule; the static
      `formula` shelf is a reasonable fallback and should be labelled as the
      general one rather than presented as theirs.

- [ ] **G5. Proportion and emphasis in the type.** Requested as "work on
      proportionality and emphasis on key words to reveal the fashion sense".
      The faces and the scale landed on 2026-10-29; what has not is
      *within-line* emphasis — the editorial move where one or two words in a
      heading carry different weight or size from the rest.

      Note the tension to resolve before building it: the frontend-design
      guidance treats accenting a single word in a headline as one of the
      commonest generated-page tells. The version that is not a tell is
      compositional — a genuine size step, a different face, a line break
      chosen for rhythm — rather than one bolded word. Decide which, with
      examples, before touching the screens.

- [ ] **G6. More Discover imagery.** Twenty-seven collections have one cover
      each. More imagery per collection would let a tile show something other
      than the same photograph every time, and would give G4's generated sets
      something to be composed from.

      Whatever is generated inherits the rules the existing covers were
      corrected into: **one person per image**, no forced aspect ratio (the
      model returns what it returns; the covers were squashed 11% once by
      resizing), representation across the full range rather than a default,
      and couples only in the collection that is about couples.

## H. The board, and talking to people on it

Reference screenshots supplied 2026-10-29: a comparable app's home board, its
inbox, its search page, and Zara's splash. What was taken from them and what
was not is recorded in the Done section; these are the parts still open.

- [ ] **H1. Direct messages.** The inbox has a Messages section and it says
      it is not open, because the honest blocker is the same one that already
      gates community posting: **a message feature cannot ship before
      blocking and reporting do.** A private channel between strangers with
      no way to stop one of them is not a smaller version of the feature, it
      is a different and worse one.

      What is needed, in the order it has to exist: block, report, and a
      moderation path for what gets reported; then threads, participants and
      delivery; then a composer. The section and its row are already built,
      so landing this is replacing one honest row with a real list.

      Scope note from the request: messages are for "inspo advice or
      connections" — somebody asking how another person would style
      something. That is a reply-to-a-look shape rather than a general
      chat app, and it being narrow is what makes the moderation surface
      tractable.

- [ ] **H2. The search page as a board of its own.** The reference opens
      search on "Ideas for you" and "Popular" — wide labelled cards, two up,
      before anybody types. Ours opens on a masonry board of every
      collection, which is the same information with no editorial order to
      it. G2's profile and G4's cohort sets already compute what "ideas for
      you" would mean, so this is a layout rather than new machinery.

      One thing to settle first: the reference overlays its labels directly
      on the photographs, and ADR-019 rejected that for grids on Material 3's
      own advice. The resolution is not to ignore either — Material 3 permits
      it *with* a scrim, which is exactly what the feature tile already does
      for the hero. Wide two-up cards are large enough for a scrim to be
      affordable; a twelve-tile grid is not.

- [ ] **H3. A floating tab bar.** Every reference screenshot has one: a
      translucent pill over the content rather than a bar below it. We use
      `NativeTabs`, which is the platform's own chrome and is the right
      default — this would be a deliberate departure from it, and worth doing
      only with `expo-glass-effect` so it is the platform's blur rather than
      a hand-rolled translucency that looks wrong on one OS.

## I. From the Whering reference

Screenshots supplied 2026-10-29 of Whering, a wardrobe app covering adjacent
ground. What is worth taking is the *structure* — a planner, moodboards, a
profile that is a profile — rather than its look, which is a lime-on-lilac
identity this product is not.

- [x] **I1. A planner.** Plan what to wear on a date. The single largest
      missing feature in the product: the whole app answers "what should I
      wear" and had nowhere to answer it *for Thursday*.

- [ ] **I2. Weather on the planner.** The reference shows a temperature and
      a "feels like" beside the date, which is what makes a plan actionable
      rather than decorative.

      **Not built, and deliberately not faked.** `domain/regional.py` returns
      geographic style context and says in its own docstring that it returns
      weather nowhere; there is no weather provider in this service. A
      hardcoded 23°C would be the exact failure the repository rules call out
      — a fixture that reads as a live integration — on the one screen where
      being wrong about the weather gets somebody rained on.

      Needs: a provider, a key, a cache with an honest staleness window, and
      a location the user has actually consented to share. Note that
      `ADR-019`'s sibling rule already applies here — styling works from a
      city somebody types in, and device location is only requested when they
      ask for local weather.

- [x] **I3. Moodboards.** Named boards to pin inspiration into, rather than
      one flat saved collection. The saved-looks machinery is already the
      hard half: `saved_looks` persists per account, merges across devices,
      and carries a note. A board is that with a name and a cover.

      One thing to decide before building: the reference lets somebody pin
      arbitrary images they upload. That crosses into territory the
      repository rules already fence — no downloading Instagram, TikTok or
      third-party platform media, analysis on user-supplied media only — so a board may
      hold this app's own collections and the user's own photographs, and a
      pasted link is stored as a reference with attribution rather than as
      a copied image.

- [ ] **I4. A profile that is a profile.** Partially done — the identity
      header landed; the rest did not. Still owed: a public handle, a bio,
      and the counts that are not yet countable (outfits, selfies,
      lookbooks). Each of those depends on a feature that does not exist, so
      this closes as those do rather than before them.

- [ ] **I5. A centre "+" action.** Every reference screenshot has one: a
      floating primary action in the middle of the tab bar that starts the
      thing the app is for. Ours has photograph-a-garment buried in the
      Wardrobe tab. Related to H3 — both are departures from `NativeTabs`,
      and if either is done they should be done together.

## J. The community platform, requested 2026-10-31

The brief, in full, with each line marked for what it actually costs. The
order below is the brief's; the order to *build* in is at the end of the
section, because several of these are cheap only once an earlier one
exists.

**The rule that shapes all of it:** a capability the stylist or the studio
can already perform does not get its own page. It gets a way to be asked
for. Every redirect is a place somebody loses their thread.

### J1. Visual and content sharing

- [x] **OOTD feed with tagged items.** Built: `posts` with media, garment
      and product tags, fail-closed screening, and a staggered board in
      Community. Tagging a *product* works; tapping a tag opens the
      retailer.
- [ ] **Shop the Look, tap-to-expand on the image.** The data is there —
      `PostItem` already carries product and garment references — but the
      tags render as a caption line, not as hotspots on the photograph.
      Needs a coordinate per tag (`x`, `y` on the image) and a tap target
      that expands to the product card. One migration, one component.
- [ ] **Public digital closets.** A consent (`wardrobe_public`), a
      read-only view of somebody else's garments, and a decision about
      what crosses: today a garment's owner-written name never leaves the
      account, and a public closet would have to either redact it or ask
      for separate consent to show it. **Ask before building.**
- [ ] **Video layouts and reels.** The heaviest item here and the one
      least served by existing parts: capture, transcode, storage cost,
      a player, autoplay policy, and a moderation path for video that the
      image screen cannot do. Needs its own plan.

### J2. Interactive peer-to-peer styling

- [ ] **"Help me style this" threads.** This is the first feature that
      lets strangers write prose to each other, so it is gated on the
      moderation console below rather than on effort. The thread itself
      is small; the queue behind it is not.
- [ ] **Polls and voting.** Cheap and safe: fixed options, no free text,
      no moderation surface. "Which shoes for a summer wedding?" is two
      images and a tally. **Best first build in this section.**
- [ ] **Lookbook collabs.** Invite somebody to build an outfit from your
      closet. Depends on public closets (J1) for the browse, and needs a
      scoped, revocable grant rather than a blanket one.

### J3. Community engagement

- [ ] **Niche styling groups.** A group is a tag plus a feed filter plus
      a membership row. The aesthetics vocabulary already exists and is
      the natural seed for the first set.
- [ ] **Custom bio tags** (body shape, height, style subculture, palette).
      The fields exist in the avatar's stated appearance. What is missing
      is the consent to show them to strangers — the same question as
      the suggestion-discoverability one already open in section D.
- [ ] **Creator fronts.** Needs a verification decision (who verifies,
      against what) before any UI. A badge nobody checks is worse than no
      badge.

### J4. Interactive and live

- [ ] **Live shopping streams.** Out of scale for this codebase as it
      stands: ingest, a realtime comment channel, live moderation, and a
      buy path that Apple and Google both have policy on. Record it,
      do not start it.
- [ ] **Style challenges and giveaways.** A challenge is a hashtag with a
      date range and a leaderboard, which is close to free once polls
      exist. Giveaways are not: a prize draw has legal requirements that
      vary by market, and this app ships in Kenya first.

### J5. Backend and safety

- [x] **Automated moderation on posts.** Built and fail-closed: a post is
      `pending_review` until the screen approves it, and an unavailable
      screen holds rather than publishes.
- [ ] **A human moderation console.** The missing half, and the blocker
      for every free-text feature above. Reports already land in the
      `reports` table with nothing reading them.
- [ ] **Filter the feed by body type, size, aesthetic, category.** The
      cohort data exists. The filter is mostly UI, and it is the cheapest
      item in the whole brief.

### The order to build in

1. **Polls** — no moderation surface, immediate engagement.
2. **Feed filters** — data exists, pure UI.
3. **Shop-the-Look hotspots** — data exists, one migration.
4. **Moderation console** — unblocks everything with text in it.
5. **Groups**, then **Help me style this**, then **bio tags** (needs the
   consent decision), then **collabs** (needs public closets).
6. **Challenges**, once polls are in.
7. **Reels** and **live** get their own plans, or are dropped.

### Open questions, which block the items that name them

- **Public closets:** does a garment's owner-written name cross to a
  stranger, or is a public closet taxonomy-only?
- **Bio tags:** showing body shape and height to strangers is a separate
  consent from being discoverable at all. One toggle or two?
- **Giveaways:** which markets, and who carries the legal obligation?

### Open after the brand studio

- **Video.** Blocked rather than planned: no model this service can reach emits
  it. Unblocking means a second vendor, which is a provider-registry entry, a
  price, a capability declaration and a cost ceiling - not a feature flag. Worth
  revisiting only when a brand asks for it twice.
- **A frame cannot be composited from two images.** Putting *this* product on
  *that* reference's set needs two inputs in one call, and the endpoint takes
  one. The reference contributing words is the honest version of this, and the
  limit should be re-checked whenever the vendor's edit endpoint changes.
- **A cast is chosen per story, not per frame.** Four frames of a launch all
  carry the same person. Per-frame casting is a schema change and a UI, and
  nobody has asked for it.
- **A story cannot be re-run with an edited brief.** The prompt is stored on
  every frame, so this is a copy-with-changes rather than new machinery, but the
  route does not exist yet.
- **Nothing reads back whether a frame kept the product.** The clause is last in
  the prompt and the tests pin the ordering, but no check compares the result
  against the source. A perceptual diff against the source photograph would
  catch an edit that redrew the garment, and would be the only automated check
  on the thing the whole feature promises.

## E. Deferred by request

- [x] **E1. Sorting still feels slow.** *Settled, and the measurement
      reversed the plan.*

      It never finished at all to begin with. `install_dispatcher()` was never
      called, so jobs were written and never dispatched; no worker was
      running; and one worker served all four queues, so the job that ends the
      spinner waited behind the slowest. With those fixed it sorted in
      **8.2-13.1s**.

      Then the detector's own answer stopped being thrown away. It already
      classifies a photograph that holds one garment, and `categorise` was
      asking the same question again. It now sees the garment is sorted and
      returns **without calling a model at all**: 0.03-0.14s, against 5-11s
      before. That is one of the two paid calls per upload, gone.

      **The remaining trade is settled: the handicap stays.** Setting
      `CATEGORISE_HANDICAP_SECONDS = 0` restores the race and makes both
      calls on every upload, and the latency it buys back was measured under
      a second. Doubling the spend on every upload for a difference nobody
      can perceive is the wrong side of that trade.

      **What the measurement actually found.** `scripts/measure_detection.py`
      ran fourteen real photographs through the live detector, which is
      twelve more than either number here had ever rested on:

      * **Detection takes 3.1-12.8s**, not the "roughly 7-9s" the handicap was
        sized from. The worst case was *already past the 12s handicap*, and
        three of the fourteen were within 2.5s of it. Every overrun pays for
        the call the handicap exists to avoid. Raised to **20s**, which the
        failure path pays for and the common path does not.
      * **The token ceiling was nearly too low, not four times too high.**
        This backlog said to lower `OUTFIT_MAX_TOKENS` "from the safe ceiling
        to the measured floor". Completions ran 763-**3460** tokens, mean
        1549, leaving 1.18x headroom at 4096. The worst case was a two-person
        photograph and nothing stops anyone uploading one; one token over and
        the model returns empty with `finish_reason: length`, which this
        codebase has already shipped three times at 512, 1200 and 2048.
        **Raised to 8192.** Following the plan here would have caused the bug
        it was trying to optimise around.
      * Reasoning is most of a completion — 1453 of 1526 on a single dress —
        and the vendor reports it as a *breakdown* of `completion_tokens`
        rather than in addition, so one ceiling bounds both. The first version
        of the measuring script added them and made the ceiling look half as
        generous as it is; verified against the adapter's mapping rather than
        assumed.

      What is left is the floor of a single vision call, and the latency is
      the reasoning: a single-garment photograph is 3-9s, a full outfit 6-13s.
      A cheaper prompt for the single-garment case would need to know it is
      one garment before calling, which is the question the call answers.

## D. Blocked or needs a decision

- [x] **D1. Keycloak has never imported this realm.** It has now. The realm
      imports, discovery serves, and the `${GOOGLE_CLIENT_ID}` substitution
      works: the Google provider carries the real client id with
      `trustEmail` still false.
- [x] **D2. Expo Go redirect URI is not registered.** The realm accepts
      `exp://*` now, marked development-only; a deployed realm must not carry
      it. Web entries moved to 19000, because Windows reserves 8011-8410 and
      Metro cannot bind 8081 on this machine.
- [x] **D3. Two Postgres-marked tests have never run.** Both pass now, and
      they earned their keep immediately: a self-referencing foreign key
      generated a 64-character constraint name against PostgreSQL's 63-char
      limit, which SQLite does not enforce, so 719 tests passed while
      `alembic upgrade head` failed on the first real database it met. They
      also shared a database — `test_jobs` drops the tables but leaves
      `alembic_version`, making the migration test's `upgrade head` a no-op.
      Separate database now, and the migration test resets its own schema.
- [x] **D4. Community is a placeholder.** It is a screen now. Posting,
      following and other people's looks still need a backend that does not
      exist, and faking that would be the most dishonest thing this app could
      do, so none of it is invented. What the tab shows instead is real and
      already yours: the looks you kept, what each is worth to you (how many
      of its pieces you own), and the way to bring one in from a link. The
      part that is not open says so in a footer, in its own words, rather than
      being implied by an empty list.

---

## Done

Moved here as items complete, newest first.

### 2026-10-31, later still

- **The `+` is a create sheet.** Pin, Collage, Board, as three doors
  rather than a route straight into a composer. Pin opens the camera
  roll first, because a pin *is* a photograph: the composer follows with
  the picture already on it.
- **A collage editor.** A canvas of placed pictures with drag, pinch and
  rotate on the UI thread, bounded undo and redo over whole states,
  six quiet backgrounds, and a picker sourcing from saved fits, boards
  and the camera roll. It exports a flattened picture and hands it to
  the composer, so a collage is a fit by the time it leaves - every
  surface that can show a photograph can show one without knowing what
  a collage is. 17 tests on the model, where undo goes wrong.
- **Search is built from real photographs.** `GET /v1/feed/explore`
  returns two rows of tiles, each a hashtag wearing the best fit
  actually under it, ranked by the same score the board uses. The
  screen had been showing generated cover art for the app's own
  taxonomy, which made the one place for finding what people posted a
  catalogue of pictures nobody posted.
- **The camera in the search field searches.** It read a garment into
  the wardrobe, which is useful and is not what the icon promises. It
  now reads the clothes out of the picture and lands on the strongest
  tag's page, saying what it thought it saw. There is no image index:
  the picture becomes words and the words are searched, which is the
  honest version and the explicable one.

### Open after the collage editor

- **No text, drawing or stickers on a canvas.** The reference has all
  three. Each is its own layer type, its own toolbar and its own export
  path; the picture layer is the one that makes a collage a collage and
  is what shipped.
- **A collage is flattened on save and cannot be re-edited.** The
  layout is not stored, so "edit this collage" would mean rebuilding it
  from an image. Storing the layout is a table and a migration, and
  worth it only once somebody asks to come back to one.
- **No remixing.** The reference offers "allow others to use your
  collage". That needs the layout stored, a permission on it, and a
  provenance chain - three things, none of which exist.

### 2026-10-31, later

- **Comments.** Model, domain, fail-closed screening, blocks applying both
  ways, counts over what each reader can see, delete by the writer or by the
  fit's author. Closed on the page behind a count; the whole thread opens in
  its own scrollable sheet with the composer pinned, so a fit with forty
  comments is not a fit you scroll past forty comments to leave.
- **The community guidelines are data.** Eleven rules in one list that the
  screen enforces, the report form offers, a held item quotes and
  `GET /v1/community/guidelines` serves. They used to be a sentence inside a
  prompt, which meant three different sets of rules and no way for anybody to
  read any of them.
- **Obvious breaches are refused in 0.03s with no model call.** A phone number
  or a shop link cannot be a remark about clothes. The detector is narrow by
  design: it never holds what the model would have passed.
- **Reports name a guideline**, and a comment can be reported.
- **Hashtags are tappable**, opening a page of everything under them with
  related tags at the top. Its own query, with no recency window - the board's
  slice would have returned a near-empty page for most tags.
- **A fit carries a link to itself**, and sharing sends it with the picture.
  Scheme from configuration, never a literal naming the product.
- **The Community tab is gone.** It was a second feed of the fits Discover
  already ranks better. Followers and following moved to the profile as a
  tappable line opening a two-tab searchable list.
- **Discover has a masthead**: the brand name from `branding.config.js`, a `+`
  that posts, and the inbox. Posting now takes a photograph from the phone -
  the composer only ever offered the app's own curated artwork as a fit's
  picture, which made the `+` a way to republish stock.
- **A member's page shows what they made.** It carried a follower count, a
  Follow button and a gift form while saying nothing about the hundreds of
  photographs its subject had published. Banner, handle, bio, both counts, and
  Created/Saved tabs over a grid.
- **Profiles have banners**, screened on the image screen like a caption.
- **An avatar can be built from your own photograph**, behind its own
  `likeness` consent - separate from `ai_processing`, because a face is not a
  wardrobe. Re-checked on the worker, so a consent withdrawn between asking
  and drawing stops the draw.
- **The studio is on the garment's page.** Four treatments and the shots they
  produce, where the photograph they act on actually is. Live-verified: a real
  khaki top cut out onto white in 50 seconds, bed and duvet gone.
- **The cut-out reaches the app.** Background removal had been working all
  along and writing a second asset; nothing on the device ever fetched it, so
  every garment kept its camera-roll picture. Two fixes: the upload flow waits
  briefly, and a sweep catches the ones that land later.

### 2026-10-31

- **The brand studio: a set of visuals from one product.** `fash.studio`
  capabilities, built on the garment studio rather than beside it, because a
  brand frame *is* an edit of a photograph the brand owns - same ownership
  check, same billing, same storage, same tombstone. What a story adds is a
  brief, a cast, an optional reference and an order. Seven scenes, four
  ready-made sets. `app/domain/brand_studio.py`, `app/workers/brand_studio.py`,
  `/v1/studio/stories`.
- **Video is blocked, and the API says so with the reason.** Every model
  reachable here declares `video_in=True` and none emits video, so there is no
  honest way to return a clip. `/v1/studio/capabilities` returns
  `video: "blocked"` and the reason, rather than leaving a client to render a
  button that cannot work. Asking the assistant for one is answered in words.
- **A reference fit contributes words, not pixels.** The vendor's edit endpoint
  takes one image, so a fit from Discover cannot be composited with a product.
  It is read into a styling note - light, palette, layering, never the person -
  and the note rides into the prompt. Both the fit's id and the note are stored
  and returned, so a brand can see exactly how much of the reference reached
  the picture.
- **The assistant is one input box.** The stylist screen carried a display
  header, a bordered status card, two labelled sections, a treatment grid, a
  prompt row and a dress-code row above the button: six pieces of furniture
  before the thing somebody came to do. All of it is gone except the composer.
  The capabilities did not go away - they moved behind the sentence, routed on
  the worker by `app/domain/assistant.py`. The dress-code signal survived too,
  read out of the words instead of picked from chips.
- **Routing costs nothing on an ordinary request.** With nothing attached, no
  intent other than styling is possible, so classification returns by
  elimination without a model call. The first version billed one on every
  "what should I wear on Friday", which a test now prevents.
- **Captions name the clothes.** One vision pass per fit reads the pieces, an
  outfit sentence, a caption and tags off the photograph. The caption is what
  makes a fit findable by what is in it; the tags are what put it in a group
  people browse; the outfit sentence is what the avatar wears. An author's own
  caption is never overwritten. `app/workers/fit_vision.py`,
  `scripts/describe_seeded_fits.py`.
- **"Try it on" under a Discover fit actually tries it on.** It used to
  navigate to the avatar screen, which can only dress somebody in a *curated
  look* - so a fit, which is a photograph, arrived with nothing to put on and
  the button did nothing. Now the fit is the request: `POST
  /v1/feed/{post_id}/try-on` writes a render carrying the post, and the worker
  reads the clothes out of the photograph and draws them on the asker's avatar.
  Live-verified end to end: queued, running, ready with a real asset in 35
  seconds.
- **Trying on two fits no longer collapses into one picture.** Render dedupe
  matched only the newest in-flight row against the subject, so trying fit A,
  then B, then A again paid for a third picture. The subject is now part of the
  query.
- **A picture of your avatar can be kept.** Saving goes to the camera roll with
  write-only permission. Without it the only way one left the app was a
  screenshot, which carries the status bar and the tab chrome and none of the
  resolution.
- **Boards hold published fits, not only curated looks.** The `...` sheet on
  Discover offered a save that could not work, because a pin was a collection's
  string id. A pin now points at one look or one post, with a check constraint
  so a row meaning two things or nothing fails at write time.
- **The Taste tab is gone from the profile**, and the three that remain sit
  centred under the portrait.

### 2026-10-29

- **G3 + G4. Cohorts, and the shelf they make affordable.** Generating fresh
  inspiration per user per week is a bill that grows with sign-ups. Grouping
  people by what kind of wardrobe they have makes it grow with the number of
  distinct *kinds* of wardrobe instead.

  * **A signature, not a clustering algorithm.** No k-means, no embeddings,
    no training. The key is assembled from facts `domain/profile.py` already
    computes, which makes it deterministic, stable (a new sign-up never
    relabels anybody), explainable in a sentence to the person it describes,
    and checkable by them. A learned clustering would find structure nobody
    anticipated and lose every one of those.
  * **The privacy property is structural, not careful.** A key holds garment
    *category* counts and a stated dress code — no garment id, no
    photograph, no name, nothing anybody typed. `cohort_inspirations` has no
    `user_id` column and must never get one. A feature cannot leak a
    wardrobe through something that never held one, and both facts are
    asserted against the stored rows rather than against the code that
    writes them.
  * **A cohort of one is not a cohort.** Below three people the key widens
    rather than being used — the same floor trending enforces, for the same
    reason. The ladder drops the dress code first (the part somebody may
    simply never have answered) and bottoms out at everybody, so there is
    always an answer.
  * **Generation walks the whole ladder.** Caught while writing the tests:
    generating only for exact keys would have left a widened group of five
    on the general shelf while a real group existed one rung up, and
    widening would have changed nothing but the number `resolve` reports.
  * **A window, not a sort by recency.** Without the range check the newest
    row is always current, so a shelf meant to refresh twice a week silently
    never expires. A set generated early for the next window also must not
    become current when it is written.
  * **Never an empty shelf, never a false claim.** `Inspiration.personalised`
    is false for the general ordering, and the API returns it, so a client
    rendering the two identically is making a claim the data does not
    support. Monday and Thursday at 03:00 UTC, cohorts recomputed before
    anything is generated for them, in one task so the ordering cannot be
    lost.

- **The board, from the supplied reference.** The reference app's home, inbox and
  search, and Zara's splash.

  * **A masonry board.** Tiles of one height are scanned row by row;
    staggered ones are scanned as a surface, which is how somebody browses
    clothes rather than reads a list. FlashList's own masonry, so recycling
    survives a long board — the hand-rolled two-column split is why
    home-made masonry stutters. Heights come from hashing the collection id,
    so a board never reflows on scroll or looks different each launch, and
    the two steps are both portrait: the covers are 2:3, so one step is the
    uncropped picture and the other trims an eighth from the centre, which
    takes floor and ceiling rather than head and feet.
  * **An inbox, reached from the masthead.** A speech bubble rather than a
    bell, because the inbox holds what people said as well as what happened
    and a bell names only the second. The badge is a number rather than a
    dot — "you have four" costs the same space as "you have something" and a
    bare dot is the badge people learn to ignore first.
  * **Two sections, not one merged list.** A message waits for a reply; an
    update is something the app did. Sorted together by time the first is
    buried under the second within a week.
  * **What was deliberately not taken.** The reference overlays labels
    directly on photographs in its grids; ADR-019 rejected that on Material
    3's own advice and the tile already implements the considered version
    (overlay on the hero where a scrim is affordable, below the image on a
    grid). A screenshot is not a reason to overturn a measured decision —
    see H2, where wide two-up cards make the scrim affordable again. Zara's
    full-bleed wordmark over the photograph is a brand splash rather than
    navigation; the restrained version of it is already the welcome screen.
  * The 8-point grid test earned its keep immediately, catching a `gap: 2`
    and a `paddingHorizontal: 4` in the inbox code within minutes of it
    being written.

- **G2. A taste profile, from the three signals that disagree.** Stated
  answers, what somebody owns, and what they reach for. The rule for which
  one leads is written in `domain/profile.py` rather than decided per
  feature, because they contradict each other constantly and averaging them
  serves nobody:

  * *How to wear what you own* — **owned leads**. Suggesting layering to
    somebody with no layers is a shelf about a different person, and it looks
    exactly as personalised as a right answer.
  * *The look* — **reached-for leads**, seeded by the stated answers so day
    one is not empty. A stated answer survives once taps exist, or answering
    the sign-up questions would visibly do nothing.
  * *Where you are going* — **stated leads**. Nothing inferred beats being
    told.

  Two bugs found by writing the tests, both of which would have shipped as
  plausible behaviour:

  * **Scoring by fraction rewarded the collections with the least evidence.**
    `denim` rests on one garment category and `layering` on four, so one pair
    of jeans was a *perfect* denim match that outranked a wardrobe full of
    knitwear, jackets and shirts — a shelf chosen because its rule was short.
    Ranked by met-category count now, with the fraction as a tiebreak.
  * **A capsule boost of 1.0 beat a complete match**, so every small wardrobe
    got the same answer whatever was in it. Replaced with an explicit rule: at
    or under twelve pieces `capsule` leads outright, because twelve pieces of
    pure tailoring and twelve of nothing in particular have the same
    most-useful answer.

  Three queries, no model call, so it is safe to ask for on every Discover
  open. The conclusion crosses the wire, not the signals — a client has no
  use for somebody's garment counts and every reason not to hold them.

- **The style classifier, measured on the full corpus and deliberately not
  shipped.** The documented next step was a 225-image run "once the sample
  stops moving". It has, so it ran, and it changed the conclusion.

  * **50.2%, not the 57.5% the 40-image sample said.** Every prompt decision
    before now was made on three-to-five point differences measured on a
    sample whose own error is larger than that.
  * **Two labels are eating the rest.** `streetwear` is predicted 1.95x as
    often as it is true and `elegant` 1.82x, while `casual` runs at 0.31x and
    `sport` at 0.41x. It is not uniformly mediocre; it is confidently wrong in
    one direction.
  * **Confidence carries no information, now measured rather than asserted.**
    Not one of 225 answers came back under 0.5. Mean 0.921 when right against
    0.895 when wrong, ranges almost entirely overlapping. There is no
    threshold, so "show it only when confident" would show wrong styles at the
    same rate as right ones while implying it had filtered them.
  * **A quarter of the error is the taxonomy.** Merging the pairs a labeller
    could defend either way lifts it to 75.1% — which is *not* a score a
    five-class prompt would get, only evidence that the taxonomy is where to
    look next.
  * So it is **wired to nothing**, and `docs/STYLE-CLASSIFICATION.md` records
    that as a decision with the numbers behind it. The harness earned its
    keep anyway: it turned a number that was never real into one that is, and
    caught a prompt change that read like an improvement and was not.

- **The brand left Discover for the welcome screen.** The wordmark sat at the
  top of the screen somebody opens twenty times a day, taking the place of
  something useful. Discover greets by name now, the way every board app in
  the reference material does, and falls back to "Discover" only while signed
  out — the one case where naming the tab beats an empty space.

  **Signing out goes to the welcome screen**, with `replace` rather than a
  push: a signed-out person pressing back into a wardrobe that can no longer
  load is a worse ending than the screen they just left.

  The welcome screen is now the only place the brand appears, so it got the
  room: the wordmark is 68px, larger than any heading in the app, and it
  still opens out of wide tracking rather than fading.

  **The three-up strip became a collage.** A row of equal rectangles says
  "here are some images"; six prints at angles, overlapping, with a lift
  under each, says moodboard — which is what this product is, and the only
  thing on that screen that can say it before anybody reads a word. Each card
  lands out of a slightly wrong angle into its own, in sequence, the way
  prints land when somebody deals them out.

  Positions are percentages of the stage, so one arrangement holds from a
  small phone to a tablet. A test asserts every card has its own angle and
  sits inside the stage: two cards at the same rotation read as a mistake
  rather than an arrangement, and a card positioned past the edge is one
  somebody only ever sees half of.

- **Profile went from nine sections to three.** Inbox, Connection, AI and
  the informational Privacy rows went with the destinations. The inbox has
  an icon in the Discover masthead carrying its unread count, so a row
  repeating it was a second front door; Connection was a backend health
  check, which is a diagnostic rather than something a person acts on; AI
  and the Privacy rows were static text stating defaults nobody had asked
  about.

  **One row was kept out of that sweep, deliberately.** The styling consent
  is a *control*, not information — the only way to withdraw AI access in
  the app — and About's "Privacy policy" is a link to a document rather than
  a duplicate of it. ADR-019's own rule is that a consent harder to withdraw
  than to grant was not freely given, and burying the withdrawal is how that
  happens by accident. It moved into Account beside the other things
  somebody does to their account, rather than being deleted with the section
  it happened to sit in.

- **The destinations moved out of Profile.** Plan, Taste, Saved, Boards and
  the avatar were five sections of rows sitting between the wardrobe counts
  and the consent switches. That made Profile a settings screen with
  destinations buried in it: the things somebody opens the app to reach sat
  under the things they look at once a year.

  They are a row of five circular quick actions on Discover now, directly
  under the masthead, which is where every board app in the reference
  material puts them. A circle with a word under it rather than five more
  outlined rectangles — that is the wall this app has already been corrected
  on twice.

  Profile keeps what a profile is for: who you are, what you have, and the
  account. It also gained **style tags** under the name, from the taste
  answers — the one thing on that screen that says *who* rather than *how
  much*, and it reads the same answers the Discover action edits, so there
  is one source and two views rather than two places to say it.

- **The avatar's setup folded away.** Five rows of chips sat permanently
  between the picture and the button that redraws it, on a screen whose
  point is the picture. They are answered once and changed rarely, so they
  are behind a disclosure that shows the current answer in a line — folding
  the controls, not what was said.

- **Explanatory copy removed app-wide.** Reported as "irrelevant words just
  taking up space", and it was: a line under every heading describing what
  the thing underneath already showed.

  Gone: "27 collections, grouped by how dressed up they are", all three
  shelf blurbs, "Measured across accounts", "What people are reaching for
  this fortnight", "Try anything on it. The clothes change; you do not.",
  "Put looks together: a trip, an occasion...", "Kept to your account, so a
  new phone starts where you left off", "Discover is the same for everybody
  until you answer", and the "Generated image" disclosure.

  **Shortened rather than cut**, because the repository rule is that an
  unbuilt capability says so: the weather note on the planner, push on the
  inbox, posting on Community, and the avatar's privacy line. One line each
  now instead of three — the rule asks the capability to be labelled, not
  for the reasoning to be explained to somebody who did not ask.

  One kept as it was: the wardrobe's **"Illustrated"** badge. That one is on
  somebody's *own* garment and means the picture is not a photograph of the
  item they own, which is a thing they can act on.

- **A way back from the stylist.** Tapping "Stylist" on a look switches
  *tabs*, and a tab has no back button, so somebody arrived with no way to
  return to what they had been looking at. The asking-about card now carries
  a named return — `back()` when there is history so it lands on the exact
  look, `replace` on a cold start where pushing would stack a second copy.

- **The generated router types were corrupt**, and the cause is worth
  recording because it looks like a config fault and is not: a truncated
  fragment was appended after the closing braces, and the route list
  contained non-routes like `/../api/queries/saved`. Two Expo processes
  (`export` and `start`) had written `.expo/types/router.d.ts` at once.
  Deleting and regenerating produced a clean file with zero bogus entries.

- **The avatar's 27-second call moved onto a worker.** Asked for directly,
  and it was a real defect: every other paid model call in this service goes
  through a durable job for the reasons ADR-005 and ADR-013 record, and the
  avatar was the exception. A generate measured at 27 seconds and a try-on at
  15 to 21, both awaited inside a request handler — a connection held open
  for half a minute, a Cloud Run timeout waiting to happen, and no record of
  the work at all if the process died mid-call.

  * **202 and a render row**, created *before* the work starts. That is the
    whole of the durability: "this person asked for a picture" survives the
    worker, the broker and the model, and a failure is a row saying why
    rather than a request that timed out with nothing behind it.
  * Measured after: the request returns in **529ms** instead of 27 seconds,
    and the worker finished the draw in 16.9s.
  * **Asking twice while one is drawing is asking once.** Each duplicate is a
    paid call for a picture nobody will look at.
  * The client polls at three seconds and **stops polling when nothing is in
    flight**, so an idle screen makes no requests. Busy state comes from the
    render list rather than from mutation state, because the work outlives
    the request: a screen reopened mid-draw has to learn that from the
    server, and so does a screen reopened after a failure.

- **Height, and the sentence that carries it.** Three bands rather than a
  measurement: a number would be a measurement of a person held on a server,
  and an image model draws "tall", not 174cm.

  Two things fell out of adding it. The composed prompt read "a woman curvy
  in their forties" — adjectives after the noun, which is not English, and an
  image model handed a sentence that reads as broken draws accordingly. It is
  now "a tall curvy woman in their forties", with the article agreeing with
  what follows it. And **"average" is stored but says nothing to the model**:
  an image model handed "a person" already draws an average build, so the
  words add nothing to the picture and do not compose into a sentence. What
  somebody stated and what the prompt needs are different questions.
  `AVATAR_PROMPT_VERSION` bumped to v2, which is what attributes a change in
  the pictures to a change in what was asked for.

- **Every piece in a picture is labelled and searchable.** Tapping one opens
  a shopping search, which is the honest version of "buy this" — this app has
  no retail integration, and pretending to one would be a fixture reading as
  a live checkout.

  **The labels are what was asked for, never re-detected.** When the avatar is
  dressed in a look the garments are already known exactly; running a vision
  model over the result to find out what we just requested would pay to guess
  at something in hand. That is the same mistake the categorise-versus-detect
  race was, and it is why this needed no second model call.

- **"From your wardrobe" on a try-on.** Which of somebody's own clothes would
  work with the picture, matched on the garment category both sides already
  speak — so no model call and nothing to calibrate, and a person can check
  every row against their own cupboard. Favourites first, samples excluded,
  and **deliberately not a similarity score**: a number next to somebody's own
  jumper, uncalibrated, is a confident claim about their clothes that only
  they can disprove, and this codebase has already measured what uncalibrated
  confidence looks like.

- **The look detail stopped being a wall of boxes.** Reported from a
  screenshot: four identical full-width outlined buttons stacked vertically,
  with no hierarchy and nothing to reach for first.

  * One **filled** primary (saving, which is what people do most), then a row
    of three glyph-and-word actions. Two rows instead of four.
  * **Headers stopped colliding.** Body text was scrolling under a
    transparent bar and behind the back button. The look detail keeps its
    transparent header — it has a hero to run under it — but gained a blur
    material; every other screen draws its own masthead with nothing behind
    the bar, so transparency bought no image and cost legibility. Now solid.
  * An empty grey square was rendering for every piece with no photograph.
    Four of those down a column reads as four images that failed to load;
    nothing is better than a placeholder for something that was never going
    to be there.
  * "Not owned" was printed on every row, under a heading that already said
    "none in your wardrobe". Owning a piece is information; not owning it is
    the default.

- **Moodboards have a UI.** The server shipped tested and screenless; this is
  the half somebody can use.

  * **A board is its own cover.** It shows the first few things pinned to it
    rather than carrying an image somebody chose, which keeps making a board
    to one decision and keeps it honest — it cannot look fuller than it is.
    One pin fills the frame, two split it, more make an asymmetric grid,
    because four equal squares is a component library's idea of a collage.
  * **Pinning is a sheet, not a screen.** It is a decision taken about the
    thing you are looking at, so navigating away loses the context that
    prompted it and lands you somewhere to navigate back from.
  * **A toggle per board, not a one-way action**, so the same sheet is how
    something gets unpinned. A "Pin" that cannot un-pin sends somebody
    hunting through boards to undo a mistap. Naming a new board is in the
    same sheet, because the moment you want one is the moment you find
    something that fits none of the others.
  * A look pinned and then retired renders as "No longer available" rather
    than a gap, which somebody would read as a bug in their own board.
  * Verified live, including the case the server tests pin: removing the
    middle pin and appending a fourth gives a clean order with no collision.

- **The dev stack migrates before it serves.** Found by hitting it: the
  moodboards table did not exist, so a correct API returned 500s with the
  cause only in a log nobody was tailing.

  Two fixes, and the second is the real one. `dev-stack.sh` now runs
  `alembic upgrade head` and refuses to start if it fails. And **`alembic`
  now falls back to the application's own settings**, which read `.env` —
  without that, `alembic upgrade head` needed a variable exported into the
  shell that `uvicorn app.main` in the same directory did not, so the two
  disagreed about which database they were talking about. That disagreement
  is how a migration gets skipped.

- **The avatar was broken in the running app, and the cause was config that
  lived nowhere.** `POST /v1/avatar` failed with "Writing derivative media is
  not implemented in this build (no object-storage credential configured)".

  * `upload_storage_mode` defaults to `simulated`, and `build_media_store`
    mapped *everything except* `local_file` to the refusing store — including
    `simulated`, despite `InMemoryMediaStore` existing and declaring
    `storage_mode = "simulated"`. That mapping was simply a defect.
  * The reason it ever worked is worse than the bug: `local_file` was being
    set by an export in whichever shell happened to start the stack, so it
    evaporated on every restart. It is in `.env` now, which is where a thing
    the stack cannot run without belongs.
  * `simulated` now returns the in-memory store **as a process singleton**.
    Returning a fresh one per request would have accepted a write and then
    failed every read — a silent success followed by a confusing failure,
    strictly worse than the loud refusal it replaced.
  * **The client turned a handled error into a crash.** `mutateAsync` throws
    and nothing caught it, so a capability the server refused correctly
    reached the user as an uncaught promise rejection over the whole app.
    Both the avatar and the taste screens now catch and say what happened,
    and the taste screen stays open with the answers intact rather than
    dismissing and losing them.
  * Verified live end to end after the fix: generate 201, download 234KB of
    WEBP, try-on 201.

- **The typography left the generated-page cluster, at the owner's call.**
  Playfair Display on warm cream with Space Grotesk is, by the house
  frontend guidance's own list, two of the named tells at once. Replaced with
  **Bodoni Moda** and **Archivo** — which recovers the optical-size axis the
  previous change recorded losing, and makes the brief's original "100/200
  against 800/900" achievable for the first time, since Archivo runs the full
  range where Playfair stopped at 400. ADR-019 carries the full reasoning.

- **The board stopped being congested.** The owner reported tiles with too
  many words at too large a size. Measured rather than guessed: each tile
  carried a cue of up to 23 characters in tracked uppercase *above* a 20px
  serif title set to wrap twice — three lines of text under every
  photograph, at 170px wide. Now one line, at reading size, with no caption
  on Discover at all: a cue is a fragment of the outfit, not information
  about the collection. The uppercase eyebrow is gone app-wide, which was
  the same fix as removing a template tell.

- **I1. A planner.** The single largest missing feature: the app answers
  "what should I wear" on every screen and had nowhere to answer it *for
  Thursday*. A week strip, a day, and the look picked for it.

  * **A date, never an instant.** Stored as `DATE` and carried as
    `YYYY-MM-DD`, so a plan made in Nairobi for Thursday is still Thursday
    after landing in London. A timestamp moves it by a timezone and the
    person finds out by being dressed for the wrong day.
  * **One plan per day**, which makes planning idempotent. Somebody who
    changes for the evening is a real case this does not cover; relaxing the
    constraint later is a smaller change than untangling duplicates somebody
    accumulated by double-tapping.
  * **"Did you wear it" is three-valued.** Null is "has not happened", not
    "declined" — collapsed to false, every future plan reads as rejected.
  * **Changing the look keeps the note**, because a note is usually what the
    day is *for*, and "Dad's birthday" does not stop being true because
    somebody picked a different outfit.
  * **Planned from what you kept**, not the whole catalogue, which would make
    the planner a second Discover tab.
  * **No weather**, and that is the I2 entry rather than a gap: this service
    has no weather provider, and a hardcoded temperature on a planner is the
    one fixture that gets somebody rained on.

- **I3. Moodboards.** Named boards, distinct from saved looks on purpose:
  saving is "I like this", pinning is "this belongs with these others".

  * **Position is a column, and `unpin` compacts it.** Without compacting,
    removing the middle pin leaves a hole that the next append collides
    with, and the order then depends on which row the database returns first
    — a bug that only ever shows up on somebody else's machine.
  * **A partial reorder keeps what it did not mention.** A short list means a
    client that knows about fewer pins than exist; reading it as "delete the
    rest" is the worst available interpretation and loses work silently.
  * Names are unique per person, pinning is idempotent, and both boards and
    pins are bounded — ten thousand pins is a corrupt client, not an
    enthusiastic user.
  * Nothing stores an image, and nothing may: when boards hold somebody's own
    photograph it goes through the media pipeline that already owns ownership
    and consent, not a URL column.

- **G1. Taste questions at sign-up.** Four questions, asked once, stored as
  preferences. The shelves in Discover now reorder from the answer.

  * **The aesthetics are pictures, not words.** Asking somebody to pick
    "quiet luxury" from a list of phrases tests whether they read fashion
    blogs. The covers already exist, and a picture is the question a fashion
    app should be asking.
  * **It is not a wall.** Skip carries the same visual weight as Save,
    declining is recorded as an answer rather than leaving the question to be
    asked again every launch, and nothing about browsing changes if somebody
    never answers. Asked once after sign-in, over the tabs rather than in
    front of them, so dismissing lands on Discover.
  * **The vocabularies are served, not hardcoded.** An aesthetic the app
    offers but the server rejects is an answer refused after somebody taps
    it; one the server knows but the app never offers is a question nobody
    can answer. Both drift the moment the lists live in two places.
  * **Picking everything is refused.** Somebody who selects all twelve
    aesthetics has expressed no preference, and storing it would make their
    shelf identical to the default while looking personalised - the worst of
    both, because nobody would think to check it. The cap is six.
  * **Re-answering overwrites rather than merging**, so deselecting takes it
    back. Merge would make a choice impossible to withdraw, which is the
    asymmetry consent deliberately avoids and just as invisible.
  * The shelf ordering had a quiet bug worth naming: a bare `indexOf` returns
    -1 for a lens the order does not mention, which sorts it to the *front*.
    Extracted to `orderShelves` and pinned - a partial order now leaves the
    unmentioned shelf where it was.

- **The welcome screen earns the orchestrated entrance.** The brief asked for
  "beautiful animations that sell the story of an elite fashion app", and
  ADR-019 holds that animation competes with the photographs. Both are right,
  and the resolution is that they are talking about different screens: on the
  first screen the photographs *are* the entrance and there is no grid
  underneath for motion to pull attention from.

  So one sequence, once, on arrival: three covers settle in like prints
  landing on a table, the wordmark opens out of 14pt tracking onto the -0.8
  that `displayType(56)` sets every other 56px heading at, the claims
  stagger, the buttons land. Nothing loops — a repeating animation beside
  text is what WCAG 2.2.2 asks for a pause control for.

  * **Three covers, not one hero.** A single full-bleed portrait makes one
    person the face of the product, which this app was already corrected on
    once. The ids live in `features/onboarding/welcome.ts` so they can be
    asserted: `coverFor` returns null for an id it does not know and the
    frame then renders *nothing*, which would empty a third of the first
    screen in the product with nothing thrown. Verified by introducing a typo
    and watching the test fail.
  * **The masthead is Reanimated, not Moti**, and the reason is a real
    limitation worth recording: `MotiText` is typed off `Omit<ViewStyle |
    TextStyle, ...>`, which keeps only the keys those share, so
    `letterSpacing` — the one property this animates — is the one property it
    cannot express.
  * **Four stale tracking overrides removed.** `displayType` started
    returning its own `letterSpacing` on 2026-10-29, so every heading that
    also set one silently won: four screens at four hand-tuned values, the
    exact inconsistency the curve exists to remove, and invisible in review
    because both lines look deliberate. A test now scans for the pattern.

- **F1-F4, the elite UI brief.** The conflict F1 recorded was put to the
  product owner and they reaffirmed the brief, so ADR-019 is **amended**
  rather than quietly broken (see its 2026-10-29 section).

  * **Two faces, no system font anywhere.** Playfair Display for headings,
    Space Grotesk for labels, controls and body. Bodoni Moda is retired: a
    second didone doing Playfair's job, and three faces is one more than any
    of them can justify.
  * **The brief's weights do not exist.** Measured from the files rather than
    assumed: Playfair has nothing below 400, Space Grotesk nothing below 300
    or above 700, so "100/200 against 800/900" is unavailable in the families
    the brief names. 400 against 900 and 300 against 700 is the widest real
    spread, and `DisplayWeight`/`LabelWeight` make a medium weight a compile
    error rather than a convention.
  * **What retiring Bodoni cost, named.** It had a real `opsz` axis and
    Playfair has none. The replacement is a tracking curve — nothing under
    24px touched, large headings in about 1.5% — which fixes the spacing half
    and cannot fix stem-and-hairline contrast. Nine hand-rolled uppercase
    eyebrows across the app collapsed onto one `label` role.
  * **The 8-point grid is tested, not documented.** Every layout step is a
    multiple of 8; `half` and `one` are the only sub-grid values and exist for
    the gap inside a badge. Eleven raw literals (a `gap: 1`, three
    `paddingVertical: 3`) were snapped to the scale, and a test now scans
    every `.tsx` for a hardcoded padding, margin or gap — verified by
    introducing a violation and watching it fail. 60/30/10 is recorded as
    `SurfaceProportion` with a test that the accent never becomes a scroll
    container's background.
  * **Moti carries one layout moment, Lottie one reward.** Discover's switch
    between shelves and a search grid cross-fades with `exitBeforeEnter`, so
    exactly one list is mounted — cross-fading a FlatList over a ScrollView
    would have both measuring at once, which is the opposite of smooth on the
    screen with the most images. Lottie draws the save confirmation, a trim
    path along a vector being the one thing Reanimated does not express. Both
    collapse under Reduce Motion, and the loader rule from ADR-019 is
    untouched: the mark plays once on an action somebody took, which is the
    case WCAG 2.2.2 does not cover.
  * **F4 is a finding, not a deliverable.** Of the sources in the brief,
    **mobbin.com and figma.com/community both return 403 to any non-browser
    client**, and 21st.dev is readable but is a React/Tailwind/shadcn registry
    whose components cannot be used in a React Native app at all. Recorded so
    nobody spends an afternoon rediscovering it. The evidence this app is
    actually built on is the measured retail data already in ADR-019.

- **B7. Saved pins have their own home, and survive a reinstall.** A `/saved`
  route reached from Profile, and `saved_looks` on the server with a
  migration from the device.

  * **Both directions merge; neither replaces.** Somebody signing in on a
    second phone has a collection on each, and an overwrite either way
    destroys one silently — the loss nobody notices until they go looking
    weeks later.
  * **The device stays the source of truth for the tap.** Saving still works
    offline and resolves synchronously; the server is the durable mirror, and
    a failed write never undoes a tap that visibly worked.
  * The local store's shape changed to carry dates, and that is the one place
    in this app that can lose data in silence: a reader that does not
    recognise the old bare array returns empty, writes empty on the next
    toggle, and the collection is gone with nothing thrown. Six tests pin it.
  * **Community stopped being a private list under somebody else's name.** It
    now shows the only genuinely cross-user signal the product has — server
    trending, with the `MIN_DISTINCT_USERS` threshold it already enforced —
    and is allowed to be empty.

- **B8. A notifications inbox**, at `/notifications`, with the unread count in
  the Profile row rather than in a coloured badge (ADR-019's terseness rule).

  * **Derived, not written.** No notifications table: every event worth
    telling somebody about is already recorded by the feature that produced
    it, and a second copy written alongside is a second thing that can drift
    or be forgotten by a new code path. The cost is named rather than hidden —
    it cannot notify about something nothing records, and read state is one
    watermark per person rather than a flag per item.
  * **Nothing invents an audience.** The one cross-user item reuses
    trending's threshold, so "1 person saved this too" — the easiest
    notification to generate and the most tempting — is not sent at all. Your
    own taps are excluded, or somebody viewing their own saved look is most of
    the way to a threshold about themselves.
  * **An empty inbox stays empty.** No welcome message, no tip of the day. A
    badge that is always lit is a badge nobody reads, and that is asserted.
  * **Push is not built**, and the screen says so in its own words rather than
    leaving somebody to work out why their phone stays quiet.


- **Avatar**: outfits on a figure that looks like you, end to end.

  Generating is text-to-image (there is no photograph of you); trying an
  outfit on is image-to-image, because the point is the *same* person in the
  same pose against the same wall wearing something else. Verified live: the
  edit held the face, build, pose, backdrop, floor and shadow and changed
  only the four named pieces, in 15s.

  * **Appearance is asked, never inferred.** Presentation, build, age band
    and skin tone are stored in `preferences`, whose own rule is that a user
    statement beats an inference. Every field optional, every one with a
    "rather not say". Nothing reads any of them off somebody's clothes, which
    is the rule every other prompt in the service already follows.
  * **Stored as `avatar`, never `garment_photo`** - it is a drawing of
    someone who looks like the user, not a photograph of them, and no later
    feature should be able to confuse the two.
  * **Both model calls are explicit.** Drawing and dressing are billed, so
    neither fires on arrival, on scroll, or as a side effect of answering a
    question.
  * **The figure is measured, not assumed.** `muse-image-1.0` returns
    1120x2240 for the avatar prompt and 1280x1920 for the Discover covers, so
    the box reads the ratio off the loaded image. A fixed ratio is how the
    covers got squashed by 11% once already.
  * **Entered from three places**: Profile, "See it on you" on any look, and
    the route directly. A look carries its id through, so the try-on is one
    tap rather than a description typed from memory.
  * `outfitSentence` builds the instruction from the pieces and their
    colours rather than the title, because "Gorpcore" is a name and "olive
    weatherproof shell jacket" is an instruction. Asserted across all 27
    collections: every one yields at least two named pieces.
  * Moti's cross-fade carries the one moment that matters - the clothes
    changing on the same person. It collapses to an instant swap under Reduce
    Motion, and the waiting pulse becomes a static tint rather than a faster
    pulse.
  * A try-on is written to `cache`, not `document`: every one produces a new
    file, and a derived preview that costs one edit to redraw should not grow
    the app's permanent storage without limit.

### 2026-10-28

- **E1** *partial*: one of two model calls per upload removed; the latency
  trade that bought it is documented and reversible in one line.
- **A1** the stylist runs, and returns an outfit from clothes you own.
- **Consent** can be granted and withdrawn, which is what unblocked A1.
- **B3/B4** cut-outs and categories reach the phone.
- **B6** trending is a claim about people now, with the rules that keep it one.
- **C2** the display face is variable, with optical size tied to how large it is set.
- **D4** Community is a real screen: your kept looks, honestly bounded.
- **Profile** greets you by name, and counts the wardrobe it is a profile of.
- **E1** *partial*: sorted in 6.5-7.5s, from 8.2-13.1s.
- **B2** favourites reach the stylist, and survive the candidate cap.
- **B5** search in Discover and the Wardrobe, one shared field.
- **C3** ThumbHash placeholders, so a cut-out's transparency survives.
- **C4** empty states carry an action, chosen by why the list is empty.
- **C5** pull-to-refresh on the Wardrobe, the one list with something to fetch.
- **Occlusion rendering**: a garment the photograph hides is drawn rather than
  cut into a fragment, stored as `garment_render`, and badged "Illustrated".
- **Media delivery**: `GET /v1/uploads/local/{asset_id}`, owner-scoped, so a
  garment the server derived has a picture the app can actually fetch.
- **A5** wardrobe photos reach the API; upload, classify, cut out, merge back.
- **D2** Expo Go can complete sign-in against the realm.
- **D1** Keycloak imports the realm; Google sign-in configured and verified.
- **D3** both Postgres tests pass, having found a real 63-char identifier bug.
- **A5/B3/B4** *partial*: the media pipeline runs end to end on the server.
- **A4** sign-in screen, Google first, with the signed-in state on Profile.
- **B1** the stylist now knows which look you asked about.
- **A2** semantic colours now carry meaning on four screens, never by colour alone.
- **A3** skeletons render for the first time, in the stylist's thinking state.
- **C1** animations extended to the look detail, Profile and Stylist.
- **A1** *partial*: the Stylist composer exists; the run still needs sign-in.
