import { TabList, TabSlot, TabTrigger, Tabs, type TabTriggerSlotProps } from 'expo-router/ui';
import type { ComponentRef, Ref } from 'react';
import { Pressable, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Colors, MaxContentWidth, Radius, Spacing } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * Web variant of the tab layout.
 *
 * `NativeTabs` wraps UITabBarController and Material bottom navigation, neither of
 * which exists in a browser — so web gets the headless `expo-router/ui` primitives
 * instead. Same five routes, same order, same tokens; only the chrome differs.
 *
 * Web is a preview surface, not a delivery target (§2: "A web preview is
 * supplementary. Native builds are required."), so this is deliberately a plain
 * horizontal bar rather than an attempt to imitate a native tab bar badly.
 */
const DESTINATIONS = [
  { name: 'index', href: '/', label: 'Discover' },
  { name: 'search', href: '/search', label: 'Search' },
  { name: 'wardrobe', href: '/wardrobe', label: 'Wardrobe' },
  { name: 'stylist', href: '/stylist', label: 'Stylist' },
  { name: 'profile', href: '/profile', label: 'Profile' },
] as const;

export default function WebTabsLayout() {
  const colors = Colors[useScheme()];

  return (
    <Tabs>
      <TabSlot style={{ height: '100%' }} />
      <TabList asChild>
        <View
          style={{
            flexDirection: 'row',
            justifyContent: 'center',
            gap: Spacing.two,
            paddingVertical: Spacing.two,
            paddingHorizontal: Spacing.three,
            backgroundColor: colors.background,
            borderTopWidth: 1,
            borderTopColor: colors.border,
            width: '100%',
            maxWidth: MaxContentWidth,
            marginHorizontal: 'auto',
          }}>
          {DESTINATIONS.map((destination) => (
            <TabTrigger
              key={destination.name}
              name={destination.name}
              href={destination.href}
              asChild>
              <TabButton>{destination.label}</TabButton>
            </TabTrigger>
          ))}
        </View>
      </TabList>
    </Tabs>
  );
}

// `asChild` clones this element with a ref attached, so the component has to accept
// one. React 19 passes ref as an ordinary prop, so no forwardRef is needed — but the
// prop still has to be declared or the cloned element does not typecheck.
function TabButton({
  children,
  isFocused,
  ref,
  ...props
  // RN 0.88's strict TS API types refs as the *instance*, not the component, so
  // `Ref<View>` is rejected where `Ref<ComponentRef<typeof View>>` is accepted.
}: TabTriggerSlotProps & { ref?: Ref<ComponentRef<typeof View>> }) {
  const colors = Colors[useScheme()];
  return (
    <Pressable
      {...props}
      ref={ref}
      accessibilityRole="tab"
      accessibilityState={{ selected: isFocused }}
      style={({ pressed }) => ({
        minHeight: 44,
        justifyContent: 'center',
        paddingHorizontal: Spacing.three,
        borderRadius: Radius.full,
        backgroundColor: isFocused ? colors.accent : 'transparent',
        opacity: pressed ? 0.7 : 1,
      })}>
      <ThemedText
        type="small"
        style={{ color: isFocused ? colors.accentText : colors.textSecondary }}>
        {children}
      </ThemedText>
    </Pressable>
  );
}
