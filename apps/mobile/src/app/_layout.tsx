import { QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import {
  DeviceRegistration,
  NotificationRouting,
  PlanReminders,
} from '@/features/notifications/sync';
import { FloatingTabBar } from '@/components/ui/tab-bar';
import { queryClient } from '@/api/query-client';
import { AttentionProvider } from '@/features/navigation/attention-context';
import { Colors } from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

SplashScreen.preventAutoHideAsync();

/**
 * The screen every other screen sits on top of.
 *
 * Without this, a deep link opened from cold — a shared look, a notification,
 * an incoming share — produced a stack containing exactly that one screen.
 * There was no back button because there was nothing behind it, and no way
 * into the rest of the app short of force-quitting. Naming the anchor puts
 * the tabs underneath whatever the link opened, so Back goes where a person
 * expects it to.
 *
 * `(tabs)` matches the anchor its own layout sets for the same reason.
 * `anchor` replaced `initialRouteName`, which was removed in SDK 58.
 */
export const unstable_settings = {
  anchor: '(tabs)',
};


/**
 * Reconciles the saved collection once per app run.
 *
 * A component rather than a hook call in `RootLayout`, because it has to sit
 * inside the `QueryClientProvider` to invalidate anything, and because the
 * root must not re-render when a background sync finishes.
 */
export default function RootLayout() {
  const scheme = useScheme();

  // Every feature needs an account, so the session is what decides which
  // half of the app exists. `loading` is a third state and not a synonym for
  // signed out: a cold start restores the session from storage, and treating
  // that moment as signed out would bounce somebody who *is* signed in out to
  // the welcome screen on every launch.
  const auth = useAuth();

  // Both faces must be resolved before the first paint. The app now sets
  // every word in one of them, so a fallback render is not a heading in the
  // wrong serif — it is the entire screen in the wrong typeface, reflowing
  // once they arrive.
  const [fontsLoaded, fontError] = useFonts({
    // One variable file each rather than a static per weight. Registered
    // under a family name with no weight suffix, because the weight is an
    // axis now and baking one into the name would be a lie about what the
    // file holds.
    BodoniModa: require('../../assets/fonts/BodoniModa-Variable.ttf'),
    Archivo: require('../../assets/fonts/Archivo-Variable.ttf'),
  });

  const ready = (fontsLoaded || fontError) && auth.status !== 'loading';

  useEffect(() => {
    // Hide on a font error too. A missing face is a degraded screen; a splash
    // that never goes away is a broken app.
    if (ready) SplashScreen.hideAsync();
  }, [ready]);

  // Holding the splash avoids a flash of unstyled type, and avoids the
  // welcome screen appearing for the instant before a stored session loads.
  if (!ready) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider value={scheme === 'dark' ? DarkTheme : DefaultTheme}>
            {/* Above the bar and above every screen, because the
                screen reports the posture and the bar reads it. */}
            <AttentionProvider>
            <PlanReminders />
            {/* Without this the server has nowhere to send to, so
                every queued notification is dropped undelivered. */}
            <DeviceRegistration />
            {/* Takes a tapped notification to the screen it is about. */}
            <NotificationRouting />
            <Stack
              screenOptions={{
                headerShown: false,
                contentStyle: { backgroundColor: Colors[scheme].background },
              }}
            >
              {/* Everything, behind the account.

                  `Stack.Protected` rather than a redirect from this
                  component: a redirect returned before the navigator mounts
                  is exactly what Expo Router refuses, and routing after mount
                  would show a screen for a frame and replace it, which is a
                  visible flash. Declaring the routes inside the guard means
                  a signed-out person cannot reach them at all — including by
                  deep link, which a per-screen check in each file would miss.

                  The guard does not run while the session is restoring: this
                  component holds the splash until then. */}
              <Stack.Protected guard={auth.status === 'signedIn'} redirectTo="/welcome">
                <Stack.Screen name="(tabs)" />
                <Stack.Screen
                  name="taste"
                  options={{
                    // A sheet, not a page: it is a question asked over what you
                    // were doing, and dismissing it has to be as easy as
                    // answering it.
                    presentation: 'formSheet',
                    headerShown: true,
                    headerTitle: '',
                    headerBackButtonDisplayMode: 'minimal',
                  }}
                />
                <Stack.Screen
                  name="moodboards"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    // These screens draw their own masthead and have nothing
                    // behind the bar, so a transparent one buys no image and
                    // costs legibility the moment anything scrolls under it.
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="board/[id]"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    // These screens draw their own masthead and have nothing
                    // behind the bar, so a transparent one buys no image and
                    // costs legibility the moment anything scrolls under it.
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="planner"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    // These screens draw their own masthead and have nothing
                    // behind the bar, so a transparent one buys no image and
                    // costs legibility the moment anything scrolls under it.
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                {/* The inbox draws its own bar: the title sits
                    between the way back and the way to write, and a
                    native one would reserve a second row above it. */}
                <Stack.Screen name="inbox" />
                <Stack.Screen
                  name="stylist"
                  // It draws its own bar, like every other pushed
                  // screen here: the title is already on the page and
                  // a native header would reserve a row above it.
                  options={{ headerShown: false }}
                />
                <Stack.Screen
                  name="insights"
                  options={{
                    // **A pushed screen needs a way back.**
                    //
                    // This had no options at all, so no header and no
                    // chevron - and Insights is not a tab, so the bar
                    // at the bottom does not lead out of it either.
                    // The only exit was the system back gesture, which
                    // is not an exit somebody can see.
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    title: 'Insights',
                  }}
                />
                <Stack.Screen
                  name="closet"
                  // Every piece somebody owns, with renaming and
                  // removing. Off the wardrobe tab because a grid of
                  // a hundred and fifty garments under the assistant
                  // buries the answer it just gave.
                  options={{ headerShown: false }}
                />
                <Stack.Screen
                  name="garment-studio"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    // The screen draws its own masthead with the garment's
                    // name under it, so the bar carries only the way back.
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="settings"
                  // It draws its own bar: the title sits between the
                  // way back and nothing else, and a native one would
                  // reserve a second row above the identity card.
                  options={{ headerShown: false }}
                />
                <Stack.Screen
                  name="collage"
                  options={{
                    // The editor draws its own bar: close, undo, redo
                    // and Next. A second one above it would be two
                    // ways out of the same screen.
                    headerShown: false,
                  }}
                />
                <Stack.Screen
                  name="people/[direction]"
                  options={{
                    // The screen draws its own back control and its own
                    // two-tab heading, so a bar above it would be a
                    // second title saying less.
                    headerShown: false,
                  }}
                />
                <Stack.Screen
                  name="tag/[tag]"
                  options={{
                    // The screen draws its own large `#tag` heading, so a
                    // bar repeating it would say the same thing twice.
                    headerShown: false,
                  }}
                />
                <Stack.Screen
                  name="fit/[id]"
                  options={{
                    // No bar: the photograph runs edge to edge and the
                    // screen draws its own floating back chip over it.
                    headerShown: false,
                    // A cross-fade, not a slide, and a short one.
                    //
                    // A pin opening is the most-repeated transition in
                    // the app. Sliding in from the right says "a
                    // different screen arrived"; fading says the
                    // picture you tapped is still the subject, and
                    // paired with the hero's spring on the other side
                    // it reads as the tile growing rather than as a
                    // page change. The photograph is already in cache
                    // and already at its own shape, so there is
                    // nothing to wait for behind the fade.
                    //
                    // `animationDuration` only applies to `fade`,
                    // `fade_from_bottom`, `slide_from_bottom` and
                    // `simple_push` on iOS - it did nothing at all
                    // under the `slide_from_right` this replaced,
                    // which is why the 300 that sat here never had
                    // any effect.
                    //
                    // 120ms, because this runs in front of the hero's
                    // own spring and the two read as one movement.
                    // Together they are about a quarter of a second;
                    // at 180 against a slower spring the whole thing
                    // came to half a second and felt it.
                    animation: 'fade',
                    animationDuration: 120,
                  }}
                />
                <Stack.Screen
                  name="saved"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    // The screen draws its own masthead, so the bar carries
                    // only the way back. Not transparent: there is no image
                    // behind it, and content scrolling under an empty bar is
                    // just text under a back button.
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="avatar"
                  options={{
                    // A header, unlike the tabs: this screen is entered from
                    // three places and the way back has to be obvious from all
                    // of them.
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    title: 'Your avatar',
                  }}
                />
                <Stack.Screen
                  name="compose"
                  options={{
                    presentation: 'formSheet',
                    headerShown: true,
                    headerTitle: '',
                    headerBackButtonDisplayMode: 'minimal',
                  }}
                />
                <Stack.Screen
                  name="shop/index"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="shop/piece"
                  options={{
                    // A sheet: a question asked over the look the person
                    // was reading, and dismissing it is part of using it.
                    presentation: 'formSheet',
                    headerShown: true,
                    headerTitle: '',
                    headerBackButtonDisplayMode: 'minimal',
                  }}
                />
                <Stack.Screen
                  name="studio"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                {/* Both message screens draw their own bar: a
                    conversation's header carries who you are writing
                    to, and a native title would say it twice. */}
                <Stack.Screen name="messages" />
                <Stack.Screen name="messages/[id]" />
                <Stack.Screen name="messages/new" />
                <Stack.Screen
                  name="member/[id]"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="subscription"
                  options={{
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                    headerTitle: '',
                    headerShadowVisible: false,
                  }}
                />
                <Stack.Screen
                  name="notification-settings"
                  // It draws its own bar, like `settings`. The native
                  // one was showing an empty title, which left a
                  // floating chevron over a page that then had to
                  // introduce itself again underneath it.
                  options={{ headerShown: false }}
                />
                <Stack.Screen
                  name="profile-edit"
                  options={{
                    // A sheet: two fields somebody changes once, over the
                    // screen they were already looking at.
                    presentation: 'formSheet',
                    headerShown: true,
                    headerBackButtonDisplayMode: 'minimal',
                  }}
                />
                <Stack.Screen
                  name="import"
                  options={{
                    // Incoming shares arrive over whatever tab is open.
                    presentation: 'formSheet',
                    headerShown: true,
                    title: 'Add inspiration',
                  }}
                />
              </Stack.Protected>

              {/* The two public screens: what this is, and the way in. */}
              <Stack.Screen name="welcome" options={{ animation: 'fade' }} />
              <Stack.Screen name="sign-in" />
            </Stack>

            {/* The tab bar, over the whole stack rather than inside
                the tab group.

                Drawn inside `(tabs)/_layout` it was covered by every
                pushed screen, so opening a pin meant going back
                before you could go anywhere else. Out here it stays
                put, and `navigate` returns to a tab already in the
                stack rather than piling a second copy on top of the
                pin. It hides itself on the few screens that own
                their own bottom controls. */}
            {auth.status === 'signedIn' ? <FloatingTabBar /> : null}
            </AttentionProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
