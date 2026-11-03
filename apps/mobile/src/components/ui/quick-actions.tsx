import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Colors, FontSize, Radius, Spacing } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/** The circle's diameter. 48 keeps the whole row under one tap target tall. */
const DISC = 48;

/**
 * The five places this app actually takes you.
 *
 * **They used to live in Profile**, which had quietly become a dumping
 * ground: Plan, Taste, Saved, Boards and Avatar were rows in a list that
 * also held consents, connection status and the sign-out button. That is a
 * settings screen wearing a profile's name, and it buried every destination
 * somebody opens the app to reach under things they look at once a year.
 *
 * Here instead, directly under the masthead, where every board app in the
 * reference material puts them. Profile keeps what a profile is for: who you
 * are, what you have, and the account.
 *
 * **A circle with a word under it, not a button.** Five outlined rectangles
 * would be the same wall this app was already corrected on. The word stays
 * because an icon alone is a guess, and one word is what keeps five of them
 * across a narrow phone without wrapping.
 */
const ACTIONS: readonly {
  id: string;
  label: string;
  href: string;
  icon: SymbolViewProps['name'];
}[] = [
  {
    id: 'saved',
    label: 'Saved',
    href: '/saved',
    icon: { ios: 'bookmark', android: 'bookmark', web: 'bookmark' },
  },
  {
    id: 'boards',
    label: 'Boards',
    href: '/moodboards',
    icon: { ios: 'square.grid.2x2', android: 'dashboard', web: 'dashboard' },
  },
  {
    id: 'planner',
    label: 'Plan',
    href: '/planner',
    icon: { ios: 'calendar', android: 'calendar_month', web: 'calendar_month' },
  },
  {
    id: 'avatar',
    label: 'On you',
    href: '/avatar',
    icon: { ios: 'figure.stand', android: 'person', web: 'person' },
  },
  {
    id: 'taste',
    label: 'Taste',
    href: '/taste',
    icon: { ios: 'heart', android: 'favorite', web: 'favorite' },
  },
];

export function QuickActions() {
  const colors = Colors[useScheme()];

  return (
    <View
      accessibilityRole="menubar"
      style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
      {ACTIONS.map((action) => (
        <MotionPressable
          key={action.id}
          accessibilityRole="link"
          accessibilityLabel={action.label}
          animateEntrance={false}
          scale={0.92}
          onPress={() => {
            void tapFeedback();
            router.push(action.href as never);
          }}
          style={{ alignItems: 'center', gap: Spacing.one, flex: 1 }}>
          <View
            style={{
              width: DISC,
              height: DISC,
              borderRadius: Radius.full,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: colors.backgroundElement,
            }}>
            <SymbolView name={action.icon} size={20} tintColor={colors.text} />
          </View>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            numberOfLines={1}
            style={{ fontSize: FontSize.meta }}>
            {action.label}
          </ThemedText>
        </MotionPressable>
      ))}
    </View>
  );
}
