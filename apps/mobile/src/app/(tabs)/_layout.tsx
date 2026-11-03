import { TabList, TabSlot, TabTrigger, Tabs } from 'expo-router/ui';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { DESTINATIONS } from '@/components/ui/tab-bar';
import { Spacing } from '@/constants/theme';

/**
 * The five primary destinations (§3), as a bar that floats over the board.
 *
 * **It floats because the content underneath is photographs.** A bar docked
 * to the bottom edge draws a hard line across a staggered board and ends it
 * early; a row of chips sitting on top of it lets the pictures run to the
 * bottom of the screen, which is the whole point of a board. Every screen
 * already pads its scroll by `BottomTabInset`, so nothing is ever trapped
 * underneath.
 *
 * **Icons only.** Five labels do not fit on one line of a floating bar at
 * any readable size, and the icons are the ones the platform already uses
 * for these ideas. Each chip carries its name as its accessibility label,
 * so nothing is lost to anyone using a screen reader.
 *
 * This replaces `NativeTabs`, which wraps UITabBarController and Material
 * bottom navigation and cannot be lifted off the edge — the headless
 * `expo-router/ui` primitives are the same ones the web layout has always
 * used, so the two files are now the same shape.
 */
export const unstable_settings = {
  // Replaces `initialRouteName`, removed in SDK 58.
  anchor: 'index',
};


export default function TabsLayout() {
  const insets = useSafeAreaInsets();

  return (
    <Tabs>
      <TabSlot />
      {/* Rendered, but not seen.

          The bar people actually tap is `FloatingTabBar`, mounted at
          the root so a pushed screen cannot cover it. These triggers
          stay because they are what declares the tabs to the
          navigator - remove them and the group has no screens - so
          they are mounted and made invisible rather than deleted.
          `box-none` and zero opacity: nothing to see, nothing to
          hit. */}
      <TabList asChild>
        <View
          pointerEvents="none"
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: insets.bottom + Spacing.two,
            flexDirection: 'row',
            justifyContent: 'center',
            gap: Spacing.two,
            opacity: 0,
          }}>
          {DESTINATIONS.map((destination) => (
            <TabTrigger
              key={destination.name}
              name={destination.name}
              href={destination.href}
              asChild>
              {/* A bare view: this trigger declares the tab to the
                  navigator and is never seen. The chip people tap is
                  in `components/ui/tab-bar`, drawn once at the root
                  so a pushed screen cannot cover it - and two copies
                  of the chip would be two places to change its
                  look. */}
              <View />
            </TabTrigger>
          ))}
        </View>
      </TabList>
    </Tabs>
  );
}

