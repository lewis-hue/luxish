import { ScrollView, View, type ViewProps } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BottomTabInset, MaxContentWidth, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

type ScreenProps = ViewProps & {
  /** Wrap content in a ScrollView. Off for screens that own their own list. */
  scroll?: boolean;
  /** Remove horizontal padding — for full-bleed grids and media. */
  bleed?: boolean;
};

/**
 * Screen scaffold: theme ground, safe areas, consistent edge padding, and clearance
 * for the native tab bar.
 *
 * Exists so no screen re-derives insets or edge padding. A screen that needs a
 * different inset is a signal the token is wrong, not that this should take a prop.
 */
export function Screen({ scroll, bleed, style, children, ...rest }: ScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  const padding = {
    paddingTop: insets.top,
    paddingHorizontal: bleed ? 0 : Spacing.three,
    // Native tab bars float above content; without this the last row is unreachable.
    paddingBottom: BottomTabInset + insets.bottom,
  };

  if (scroll) {
    return (
      <ScrollView
        style={[{ backgroundColor: theme.background }, style]}
        contentContainerStyle={[padding, { maxWidth: MaxContentWidth, width: '100%' }]}
        contentInsetAdjustmentBehavior="automatic"
        {...rest}>
        {children}
      </ScrollView>
    );
  }

  return (
    <View
      style={[{ flex: 1, backgroundColor: theme.background }, padding, style]}
      {...rest}>
      {children}
    </View>
  );
}
