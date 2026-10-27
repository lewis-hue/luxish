import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  Display,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  Tracking,
} from '@/constants/theme';
import { BRAND } from '@/branding';
import { AuthError, signIn } from '@/features/auth/session';
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
export default function SignInScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
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
      router.replace('/(tabs)');
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
          paddingTop: insets.top + Spacing.six,
          paddingBottom: insets.bottom + Spacing.four,
          paddingHorizontal: Spacing.three,
          justifyContent: 'space-between',
        }}>
        <View style={{ gap: Spacing.two }}>
          <ThemedText
            style={{
              fontFamily: Display.regular,
              fontSize: 56,
              lineHeight: 60,
              letterSpacing: -1,
              color: colors.text,
            }}>
            {BRAND.name}
          </ThemedText>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.subhead }}>
            {BRAND.tagline}
          </ThemedText>
        </View>

        <View style={{ gap: Spacing.three }}>
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
                  marginTop: 6,
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

          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{
              fontSize: FontSize.meta,
              letterSpacing: Tracking.label,
              textAlign: 'center',
            }}>
            Your wardrobe stays private to your account
          </ThemedText>
        </View>
      </View>
    </>
  );
}
