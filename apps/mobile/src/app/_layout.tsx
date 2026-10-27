import {
  BodoniModa_400Regular,
  BodoniModa_600SemiBold,
} from '@expo-google-fonts/bodoni-moda';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Colors } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

SplashScreen.preventAutoHideAsync();

/**
 * One client for the app. `retry: 2` with exponential backoff rather than the
 * default, so a flaky mobile connection recovers without hammering the API; and
 * `staleTime` is non-zero because almost nothing here needs sub-minute freshness
 * (offers are the exception and set their own).
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      staleTime: 60_000,
      // The app is frequently backgrounded mid-scroll; refetching on every focus
      // burns data for no benefit.
      refetchOnWindowFocus: false,
    },
  },
});

export default function RootLayout() {
  const scheme = useScheme();

  // The display face must be resolved before the first paint, or every heading
  // renders in a fallback serif and then reflows once Bodoni arrives — a visible
  // jump on the busiest screen in the app.
  const [fontsLoaded, fontError] = useFonts({
    BodoniModa_400Regular,
    BodoniModa_600SemiBold,
  });

  useEffect(() => {
    // Hide on a font error too. A missing display face is a degraded screen; a
    // splash that never goes away is a broken app.
    if (fontsLoaded || fontError) SplashScreen.hideAsync();
  }, [fontsLoaded, fontError]);

  // Holding the splash avoids a flash of unstyled headings.
  if (!fontsLoaded && !fontError) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider value={scheme === 'dark' ? DarkTheme : DefaultTheme}>
            <Stack
              screenOptions={{
                headerShown: false,
                contentStyle: { backgroundColor: Colors[scheme].background },
              }}>
              <Stack.Screen name="(tabs)" />
              <Stack.Screen
                name="import"
                options={{
                  // Incoming shares arrive over whatever tab is open.
                  presentation: 'formSheet',
                  headerShown: true,
                  title: 'Add inspiration',
                }}
              />
            </Stack>
          </ThemeProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
