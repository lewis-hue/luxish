import { NativeTabs } from 'expo-router/native-tabs';

import { Colors } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * The five primary destinations (§3). Native tab bar — UITabBarController on iOS,
 * Material bottom navigation on Android — so the chrome is the platform's, not ours.
 *
 * Every route is declared explicitly: SDK 58 removed implicit route discovery in tab
 * layouts, so an undeclared file simply never appears in the bar.
 */
export const unstable_settings = {
  // Replaces `initialRouteName`, removed in SDK 58.
  anchor: 'index',
};

export default function TabsLayout() {
  const colors = Colors[useScheme()];

  return (
    <NativeTabs
      backgroundColor={colors.background}
      indicatorColor={colors.backgroundElement}
      tintColor={colors.accent}
      labelStyle={{ selected: { color: colors.text } }}>
      {/* Discover is the anchor, so it owns `/`. */}
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Label>Discover</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon
          sf={{ default: 'square.grid.2x2', selected: 'square.grid.2x2.fill' }}
          md={{ default: 'grid_view', selected: 'grid_view' }}
        />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="wardrobe">
        <NativeTabs.Trigger.Label>Wardrobe</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon
          sf={{ default: 'hanger', selected: 'hanger' }}
          md={{ default: 'apparel', selected: 'apparel' }}
        />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="stylist">
        <NativeTabs.Trigger.Label>Stylist</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon
          sf={{ default: 'sparkles', selected: 'sparkles' }}
          md={{ default: 'auto_awesome', selected: 'auto_awesome' }}
        />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="community">
        <NativeTabs.Trigger.Label>Community</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon
          sf={{ default: 'person.2', selected: 'person.2.fill' }}
          md={{ default: 'group', selected: 'group' }}
        />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="profile">
        <NativeTabs.Trigger.Label>Profile</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon
          sf={{ default: 'person.crop.circle', selected: 'person.crop.circle.fill' }}
          md={{ default: 'account_circle', selected: 'account_circle' }}
        />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
