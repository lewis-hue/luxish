import { Stack, router } from 'expo-router';
import { MotiView } from 'moti';
import { useState } from 'react';
import { Text, useWindowDimensions, View } from 'react-native';
import Animated from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BRAND } from '@/branding';
import { ThemedText } from '@/components/themed-text';
import { Grain } from '@/components/ui/grain';
import {
  MotionPressable,
  tapFeedback,
  useMotiSpring,
  useMotiTiming,
} from '@/components/ui/motion';
import {
  Colors,
  Display,
  Motion,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';


/**
 * The page's one orchestrated moment, in milliseconds.
 *
 *   masthead  120 ..  ~700   (spring, settles once)
 *   rule      420 ..   700
 *   button    520 ..   800
 *
 * Written out here rather than scattered through the JSX because the only
 * thing keeping this legal is the total: **WCAG 2.2.2 wants a pause, stop or
 * hide control for motion that runs past five seconds beside other
 * content**, and a pause button on a welcome screen is clutter nobody wants.
 * It now finishes comfortably inside one second.
 *
 * **What used to be here.** Twelve photographic prints dealt themselves out
 * under the wordmark, back row first, taking about 1.4 seconds. Two concepts
 * preceded even that: a drawn crowd on a globe beneath the pile, then a
 * single sketched figure buckling under it.
 *
 * All three are gone, on the product owner's instruction (2026-11-03). The
 * pile was the slowest thing on the first screen a person ever sees, and the
 * screen says what it needs to say without it: a wordmark set at the full
 * measure of the page, on grained paper, and one door. A splash screen that
 * has to show you twelve photographs before it will let you in is arguing
 * for the product rather than opening it.
 *
 * The frames themselves lived in `features/onboarding/welcome.ts` with a
 * test pinning their stagger and overlap. Both were deleted with this change
 * rather than left unrendered — see git history if the pile is ever wanted
 * back. The `Collage` component stays; `components/ui/empty-state` uses it.
 */

/**
 * The size the wordmark is measured at, before it is scaled to the measure.
 *
 * Arbitrary — the fit is a proportion — but large enough that rounding in
 * the measurement does not matter.
 */
const MASTHEAD_BASE = 92;

/** The tracking the hidden measuring copy has to carry, or it reports the
 *  width of a differently-spaced word. */
const MASTHEAD_TRACKING = -1;

/**
 * The first screen, and the only one that gets to introduce the product.
 *
 * It exists because there was no way to reach one. The app booted straight
 * into the tabs, so the brand lived on a sign-in screen nobody opened and a
 * new arrival met a grid of collections with no idea whose it was or what it
 * would do for them.
 *
 * **The name and the way in, and nothing else.** Three claims used to sit
 * under a strapline, each naming something the app does. They went because
 * they were saying in words what the pictures above them said already; then
 * the pictures went too. What is left is the oldest thing a fashion title
 * does: put the name on the page at full width and get out of the way.
 *
 * There is deliberately no strapline. "Dress well, daily" stood here once
 * and was then repeated on the sign-in screen one tap later — the same words
 * twice in five seconds. Sign-in carries the sentence now.
 *
 * **One way out, because there is only one.** Every feature is behind
 * sign-in, so the screen offers the door that exists rather than a "look
 * around first" that would dead-end on a redirect back to here.
 *
 * **This is the one screen that gets an orchestrated entrance.** ADR-019
 * holds that animation competes with the photographs, which are the content
 * — on every other screen. Here there is no grid underneath for motion to
 * pull attention from, and a first screen is the one place where a product
 * may take a moment to say what it is. It runs once, on arrival, and nothing
 * loops: a repeating animation beside text is what WCAG 2.2.2 asks for a
 * pause control for.
 */
export default function WelcomeScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const timing = useMotiTiming();
  const spring = useMotiSpring();
  const [leaving, setLeaving] = useState(false);

  // The measure: the width the content column actually occupies, which is
  // also the width of the Get started button. The wordmark is set to span
  // exactly this.
  const { width: screenWidth } = useWindowDimensions();
  const contentWidth = screenWidth - Spacing.three * 2;
  const [fitted, setFitted] = useState<number | null>(null);

  // One way in. Browsing without an account used to be the second button
  // here; every feature is behind sign-in now, so a "look around" door would
  // open onto a redirect straight back to this screen.
  const go = () => {
    void tapFeedback();
    setLeaving(true);
    router.replace('/sign-in');
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: false }} />
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          paddingTop: insets.top + Spacing.four,
          paddingBottom: insets.bottom + Spacing.four,
          paddingHorizontal: Spacing.three,
          gap: Spacing.three,
        }}
      >
        {/* A hidden copy, set once, purely to find the size that fills the
            measure.

            The visible wordmark drops in from above, so it cannot be
            measured while it is moving. This one carries the settled
            tracking and the base size, is never painted, and reports the one
            number needed: how wide `BRAND.name` is at `MASTHEAD_BASE`. The
            real size follows by proportion. */}
        {fitted === null ? (
          <Text
            // Never read aloud and never seen: the visible masthead below
            // is the heading.
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            numberOfLines={1}
            onTextLayout={(event) => {
              const measured = event.nativeEvent.lines[0]?.width ?? 0;
              if (measured > 0 && contentWidth > 0) {
                // A hair under the full measure. Scaling to exactly the
                // container width leaves nothing for rounding or for the
                // tracking, which is not scaled with the size — and a
                // single-line Text that overflows by one point does not
                // overflow, it truncates with an ellipsis.
                setFitted(
                  Math.floor(MASTHEAD_BASE * ((contentWidth * 0.97) / measured)),
                );
              }
            }}
            style={{
              position: 'absolute',
              opacity: 0,
              fontFamily: Display.variable,
              fontSize: MASTHEAD_BASE,
              letterSpacing: MASTHEAD_TRACKING,
              fontVariationSettings: { wght: 900, opsz: 6 },
            }}>
            {BRAND.name}
          </Text>
        ) : null}

        {/* The masthead, centred in everything the button and the safe areas
            left over.

            It sat hard against the top when the prints had the middle of the
            screen. With the middle now empty, a word pinned to the top edge
            reads as a header with its page missing; centred, it reads as the
            title page it is. */}
        <View style={{ flex: 1, justifyContent: 'center', gap: Spacing.two }}>
          {/* The wordmark drops in.

              Two earlier versions were wrong in different ways. It settled
              out of 14pt of tracking first, which works while the word is
              narrower than the measure and breaks the moment it fills it —
              14pt across six letters is seventy points of extra width the
              line has nowhere to put, so a wordmark set to span the column
              spent the animation truncated to "LUXis…". Then a sheet in the
              page colour slid off it, which preserved the width and was slow
              and inert to watch.

              It falls instead: a spring, about half a second, with enough
              weight to settle rather than glide. `translateY` changes nothing
              about the line's width, so the fitted size is safe. */}
          <MotiView
            from={{ translateY: -(fitted ?? MASTHEAD_BASE), opacity: 0 }}
            animate={{ translateY: 0, opacity: 1 }}
            // Stiff and lightly damped: it arrives fast and settles once.
            transition={spring({ damping: 13, stiffness: 240, mass: 0.85, delay: 120 })}>
            <Animated.Text
              accessibilityRole="header"
              numberOfLines={1}
              style={{
                fontFamily: Display.variable,
                // Sized to the measure: the wordmark spans exactly the width
                // the Get started button does, which is what makes it read as
                // a masthead rather than as a large word. Falls back to the
                // base size for the frame before the measurement lands.
                fontSize: fitted ?? MASTHEAD_BASE,
                // 1.2, not 1.04. A didone at weight 900 has ascenders well
                // clear of its cap height, and a line box barely taller than
                // the point size crops the top of the letters off — which is
                // not something `displayType`'s leading curve covers, because
                // this masthead sets its own size outside it.
                lineHeight: Math.round((fitted ?? MASTHEAD_BASE) * 1.2),
                color: colors.text,
                textAlign: 'center',
                // The heavy end of the weight axis, and the *low* end of the
                // optical one, which is the part that matters here.
                //
                // A didone's optical-size axis controls stroke contrast: the
                // large-size cuts are drawn with finer hairlines because at
                // display size that is what looks refined. Left to its own
                // devices at this size, Bodoni thinned the crossbar of the X
                // and the thin sides of the U to the point of vanishing. opsz
                // 6 is the bottom of this file's range (6-96, default 11),
                // so it is the sturdiest cut the family has: set at 92px it
                // keeps the drama of the heavy stems while leaving the thin
                // strokes actually there. Note the default is 11, not the
                // font size — this is a real reduction, not a no-op.
                fontVariationSettings: { wght: 900, opsz: 6 },
              }}>
              {BRAND.name}
            </Animated.Text>
          </MotiView>

          {/* One hairline, drawn across the measure.

              The single piece of structure on the page, and it is doing a
              job rather than decorating: it states where the measure ends,
              which is what turns a large word floating in the middle of a
              screen into a masthead sitting on a page. It is also the oldest
              device in the trade for exactly that.

              It wipes out from the centre once the wordmark has landed —
              never before, or the rule is drawing a line under a word that
              has not arrived. */}
          <MotiView
            from={{ scaleX: 0, opacity: 0 }}
            animate={{ scaleX: 1, opacity: 1 }}
            transition={timing({ duration: Motion.slow, delay: 420 })}
            style={{
              height: 1,
              backgroundColor: colors.borderStrong,
              alignSelf: 'stretch',
            }}
          />
        </View>

        <MotiView
          from={{ opacity: 0, translateY: 12 }}
          animate={{ opacity: 1, translateY: 0 }}
          // 2050 put the primary action behind two seconds of invisibility
          // while it stayed fully hit-testable — a tap on apparently empty
          // paper navigated. It arrives with the masthead now instead.
          transition={timing({ duration: Motion.slow, delay: 520 })}
          style={{ gap: Spacing.two }}
        >
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Get started"
            accessibilityState={{ disabled: leaving }}
            disabled={leaving}
            animateEntrance={false}
            onPress={go}
            style={{
              minHeight: TapTarget + 8,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.text,
              opacity: leaving ? 0.5 : 1,
            }}
          >
            <ThemedText type="smallBold" style={{ color: colors.background }}>
              Get started
            </ThemedText>
          </MotionPressable>
        </MotiView>

        {/* Paper grain, over everything rather than under it.

            It was the first child, behind the content. That turned every
            figure's silhouette mask — which is painted in the page colour to
            hide the floor behind a body — into a flat, grainless shape
            against grained paper: a visible cut-out of each person. Grain is
            a property of the printed page, not of the paper under the ink,
            so it belongs on top, where it lies over the masks and the
            photographs alike and no layer can show through it. */}
        <Grain />
      </View>
    </>
  );
}
