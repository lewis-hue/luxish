import { Stack, router } from 'expo-router';
import { MotiView } from 'moti';
import { useState } from 'react';
import { Text, useWindowDimensions, View, type LayoutChangeEvent } from 'react-native';
import Animated from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BRAND } from '@/branding';
import { ThemedText } from '@/components/themed-text';
import { Collage } from '@/components/ui/collage';
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
import { WELCOME_SHEET, WELCOME_STAGE } from '@/features/onboarding/welcome';
import { useScheme } from '@/hooks/use-theme';


/**
 * The page's one orchestrated moment, in milliseconds.
 *
 * The wordmark drops, then twelve prints deal themselves out beneath it,
 * back row first.
 *
 *   masthead  120 ..  ~700   (spring, settles once)
 *   prints      0 .. ~1370   (last card at delay 690 + 680 easing)
 *   button     520 ..   800
 *
 * Written out here rather than scattered through the JSX because the only
 * thing keeping this legal is the total: **WCAG 2.2.2 wants a pause, stop or
 * hide control for motion that runs past five seconds beside other
 * content**, and a pause button on a welcome screen is clutter nobody wants.
 *
 * Two concepts stood here before this one and are worth recording, because
 * both were asked for and both were removed for the same reason. A drawn
 * crowd stood on a globe under the pile; then a single sketched man held the
 * pile over his head and buckled under it as it landed. The figure was
 * always the hard part — line art is transparent, so it needed a silhouette
 * mask behind it to stop the photographs showing through, it could not
 * cross-fade between poses without reading as a double exposure, and at the
 * sizes that left room for it the prints were too small to see who was in
 * them. The pictures are the product. They have the screen now.
 */

/**
 * How much of the stage box the pile is allowed to fill.
 *
 * One. The pile *is* the screen now rather than a prop in somebody's hands,
 * and the box it is fitted into is already only what the masthead and the
 * button left over. This is here as a name for that decision rather than as
 * a dial — but it is the dial, if the composition ever needs air around it.
 */
const STAGE_FILL = 1;

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
 * **The name, the strapline, and the way in.** Three claims used to sit
 * under the strapline, each naming something the app does. They went because
 * they were saying in words what the pictures above them already say, and a
 * first screen that has to explain itself in a list is not introducing a
 * product so much as apologising for one.
 *
 * **One way out, because there is only one.** Every feature is behind
 * sign-in, so the screen offers the door that exists rather than a "look
 * around first" that would dead-end on a redirect back to here.
 *
 * **This is the one screen that gets an orchestrated entrance**, and the
 * reasons are specific rather than a preference for motion. ADR-019 holds
 * that animation competes with the photographs, which are the content — on
 * every other screen. Here the photographs *are* the entrance, there is no
 * grid underneath for the motion to pull attention from, and a first screen
 * is the one place where a product may take two seconds to say what it is.
 * It runs once, on arrival, and nothing on this screen loops: a repeating
 * animation beside text is what WCAG 2.2.2 asks for a pause control for.
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

  // What is left for the pile once the masthead, the button and the safe
  // areas have taken theirs — measured rather than derived from the screen
  // height, because the masthead's own height depends on how wide the
  // wordmark turned out to be.
  const [stageBox, setStageBox] = useState<{ width: number; height: number } | null>(null);
  const onStageLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setStageBox((current) =>
      current?.width === width && current?.height === height ? current : { width, height },
    );
  };

  // Fitted inside *both* dimensions. A stage with a fixed aspect ratio and a
  // full-width card overflows its box on any phone shorter than the one it
  // was tuned on — and an overflowing collage does not clip, it slides under
  // the button.
  const stageWidth = stageBox
    ? Math.min(stageBox.width, stageBox.height * WELCOME_STAGE) * STAGE_FILL
    : 0;

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
          // Near the top, but off it. Hard against the safe area the
          // masthead read as cropped rather than placed.
          paddingTop: insets.top + Spacing.four,
          paddingBottom: insets.bottom + Spacing.four,
          paddingHorizontal: Spacing.three,
          // One rhythm down the screen. `space-between` used to distribute
          // the slack, which put uneven gaps between the four blocks; the
          // sketch absorbs it now, so every gap here is the same.
          gap: Spacing.three,
        }}
      >
        {/* The name first and loud.

            It sat under the pictures, at 68, with the strapline beneath it.
            Moved to the top and set at 92 in the heavy weight: this is the
            only screen the brand appears on, the thing it has to do is be
            unmissable, and a fat didone at the top of the page is the oldest
            move a fashion title has. The strapline went with it — "Dress
            well, daily" was then repeated on the sign-in screen one tap
            later, which is the same words twice in five seconds.

            The wordmark settles out of wide tracking rather than fading in,
            so the entrance animates the typography itself instead of using
            type as a surface to fade. */}
        {/* A hidden copy, set once, purely to find the size that fills the
            measure.

            The visible wordmark animates its tracking in from 560, so
            measuring *it* returns the width of a word stretched across three
            screens. This one carries the settled tracking and the base size,
            is never painted, and reports the one number needed: how wide
            `BRAND.name` is at `MASTHEAD_BASE`. The real size follows by
            proportion. */}
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

        {/* The wordmark drops in.

            Two earlier versions were wrong in different ways. It settled out
            of 14pt of tracking first, which works while the word is narrower
            than the measure and breaks the moment it fills it — 14pt across
            six letters is seventy points of extra width the line has nowhere
            to put, so a wordmark set to span the column spent the animation
            truncated to "LUXis…". Then a sheet in the page colour slid off
            it, which preserved the width and was slow and inert to watch.

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

        {/* The stage: twelve prints, dealt out.

            This is the whole middle of the screen and it is meant to be.
            Twelve people in twelve aesthetics, none of them repeating who
            the last one was, is the product's claim made as a picture — and
            it is a claim that gets weaker the smaller you draw it.

            The cards carry their angles past the edges of this box, which is
            deliberate: a pile trimmed exactly to a rectangle reads as a
            grid. */}
        <View style={{ flex: 1, justifyContent: 'center' }} onLayout={onStageLayout}>
          {/* Nothing mounts until the masthead has its fitted size. The
              hidden measure lands one frame in and changes the masthead's
              height, which resizes this box; a collage already mid-deal at
              that moment is re-laid out in flight, and the jump reads as
              the whole screen glitching, button included. Waiting costs
              one frame and removes the only layout shift the entrance
              could collide with. */}
          {fitted !== null && stageWidth > 0 ? (
            <View style={{ width: stageWidth, alignSelf: 'center' }}>
              <Collage frames={WELCOME_SHEET} aspectRatio={WELCOME_STAGE} entrance="deal" />
            </View>
          ) : null}
        </View>

        <MotiView
          from={{ opacity: 0, translateY: 12 }}
          animate={{ opacity: 1, translateY: 0 }}
          // 2050 put the primary action behind two seconds of invisibility
          // while it stayed fully hit-testable — a tap on apparently empty
          // paper navigated. It arrives with the pictures now instead.
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
