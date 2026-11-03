import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { useWindowDimensions, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { DetailStrip } from '@/components/ui/detail-strip';
import { Grain } from '@/components/ui/grain';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { AuthError, signIn } from '@/features/auth/session';
import { hasAskedTaste } from '@/features/onboarding/taste';
import { useScheme } from '@/hooks/use-theme';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

/**
 * Sign in, with Google first.
 *
 * Google leads because it is the only route most people will take, and burying
 * it under an email form costs every one of them a tap. The email route is
 * present and secondary rather than absent: an app that offers exactly one
 * identity provider locks out anyone who does not have that account.
 *
 * Nothing here handles a password. Both buttons open the system browser and
 * hand off to Keycloak, which is a security requirement rather than a
 * shortcut: an in-app WebView could read a Google password as it is typed,
 * which is the attack federated sign-in exists to prevent, and is why Google
 * refuses WebView traffic outright.
 *
 * There is no "skip" or "continue as guest". The app is a personal wardrobe;
 * everything it does is tied to the clothes you own, so a signed-out mode
 * would be an empty shell pretending to be a product.
 */
/**
 * Broken by hand, not by the container.
 *
 * Left to wrap, the line falls wherever the phone is wide — "Everything
 * you own, in" over "one place" on one device and something else on the
 * next. Broken on the comma it sets as two balanced lines on every
 * screen, which is the whole of a display setting.
 */
const HEADLINE = 'Everything you own,\nin one place';

export default function SignInScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  // A third of the screen, and it runs under the status bar: the crops start
  // at the very top of the display rather than below the notch, which is what
  // makes them read as a printed page instead of a banner.
  const { height: screenHeight } = useWindowDimensions();
  const strip = Math.round(screenHeight * 0.34);
  const [busy, setBusy] = useState<'google' | 'email' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = async (withGoogle: boolean) => {
    void tapFeedback();
    setBusy(withGoogle ? 'google' : 'email');
    setError(null);
    try {
      await signIn({ withGoogle, selectAccount: withGoogle });
      // `replace`, not `push`: the sign-in screen must not sit in the back
      // stack, or the hardware back button returns a signed-in user to it.
      router.replace('/');
      // Then the taste questions, once, over the tabs rather than in front
      // of them. Pushed after the replace so dismissing the sheet lands on
      // Discover rather than back on sign-in, and only ever asked once —
      // a one-time question that reappears every launch is nagging, and a
      // person who skipped has already answered.
      if (!hasAskedTaste()) router.push('/taste');
    } catch (caught) {
      // Backing out of the browser is a decision, not a failure, and showing
      // an error for it teaches people that the app is broken.
      if (caught instanceof AuthError && caught.code === 'cancelled') return;
      setError(
        caught instanceof Error ? caught.message : 'Sign-in could not complete.',
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Stack.Screen options={{ headerShown: false }} />
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          paddingBottom: insets.bottom + Spacing.four,
          // No horizontal padding: the crops bleed to both edges, which is
          // the whole of the effect. The controls below re-add it.
          gap: Spacing.four,
        }}>
        {/* The brand name and the strapline were here, at 56 and 15. They
            were the same two strings the welcome screen had just shown, one
            tap earlier, which is why this screen read as a repeat. The crops
            say the same thing without saying it twice. */}
        <DetailStrip height={strip} />

        {/* One line, centred in whatever space is left between the pictures
            and the buttons. `flex: 1` is what closes the gap the user saw:
            the screen used to be `space-between`, which pinned the strip to
            the top and the buttons to the bottom and left a dead band in the
            middle with nothing in it. */}
        <View
          style={{
            flex: 1,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
          }}>
          {/* The roman, not the italic. This line was set in Bodoni italic
              at 30 and could not be read: a didone italic is all hairline at
              its thin strokes, and at body length on a textured ground it
              stops being a flourish and starts being a guess. The italic had
              no other home once the welcome strapline went, so it has been
              removed from the type system rather than left as an export
              waiting to catch somebody out. */}
          <ThemedText
            style={{
              // 900, the heavy end of the axis. At 400 this sat on the page
              // as a caption rather than a statement.
              ...labelType(30, 800),
              // Explicit, or a heavy weight at this size clips its
              // own ascenders.
              lineHeight: 36,
              color: colors.text,
              textAlign: 'center',
            }}>
            {/* No word here is emphasised differently from its
                neighbours: a single accented word in a headline is one of
                the most recognisable generated-page tells, and this type
                system carries contrast between roles, not inside a line. */}
            {HEADLINE}
          </ThemedText>
        </View>

        <View style={{ gap: Spacing.three, paddingHorizontal: Spacing.three }}>
          {error ? (
            <View
              style={{
                flexDirection: 'row',
                gap: Spacing.two,
                alignItems: 'flex-start',
              }}>
              {/* A dot rather than a tinted banner. The washes available on
                  warm paper compute to around 1.1:1 against the page, so they
                  add markup and no signal, and a coloured left rule is one of
                  the most recognisable generated-UI tells. */}
              <View
                style={{
                  width: 6,
                  height: 6,
                  marginTop: Spacing.two,
                  borderRadius: Radius.full,
                  backgroundColor: colors.danger,
                }}
              />
              <ThemedText
                type="small"
                style={{ flex: 1, fontSize: FontSize.footnote, color: colors.danger }}>
                {error}
              </ThemedText>
            </View>
          ) : null}

          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Continue with Google"
            accessibilityState={{ busy: busy === 'google', disabled: busy !== null }}
            disabled={busy !== null}
            animateEntrance={false}
            onPress={() => void start(true)}
            style={{
              minHeight: TapTarget + 8,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.text,
              opacity: busy !== null ? 0.5 : 1,
            }}>
            <ThemedText type="smallBold" style={{ color: colors.background }}>
              {busy === 'google' ? 'Opening Google' : 'Continue with Google'}
            </ThemedText>
          </MotionPressable>

          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Use email instead"
            accessibilityState={{ busy: busy === 'email', disabled: busy !== null }}
            disabled={busy !== null}
            animateEntrance={false}
            onPress={() => void start(false)}
            style={{
              minHeight: TapTarget + 8,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderColor: colors.borderStrong,
              opacity: busy !== null ? 0.5 : 1,
            }}>
            <ThemedText type="smallBold" style={{ color: colors.text }}>
              {busy === 'email' ? 'Opening' : 'Use email instead'}
            </ThemedText>
          </MotionPressable>

        </View>

        {/* Over the content, not under it — see `Grain`. */}
        <Grain />
      </View>
    </>
  );
}
