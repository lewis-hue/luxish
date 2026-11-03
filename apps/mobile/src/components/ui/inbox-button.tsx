import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { View } from 'react-native';

import { useMessages } from '@/api/queries/messages';
import { useInbox } from '@/api/queries/notifications';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable } from '@/components/ui/motion';
import { Colors, FontSize, Radius, Spacing, TapTarget } from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

/**
 * The way into the inbox, from the masthead.
 *
 * A speech bubble rather than a bell. The inbox holds two kinds of thing —
 * what people said and what happened — and a bell names only the second,
 * which would make the messages half look like an afterthought the first
 * time somebody goes looking for it.
 *
 * **The count is a number, not a dot.** "You have something" is less useful
 * than "you have four", costs the same space, and a bare dot is the badge
 * people learn to ignore first. Capped at 9+ because past that the exact
 * figure stops changing what anybody does.
 *
 * **It counts both halves, which it did not.** The glyph is a speech
 * bubble and the screen behind it holds what people said as well as
 * what happened - but the badge only ever counted the second. A new
 * message arrived and nothing anywhere on the app said so, which is
 * the one thing a badge on a speech bubble is for.
 *
 * Shown signed out too, leading to a screen that explains why it is empty.
 * Hiding it would make the inbox something people discover only after they
 * already have an account, which is backwards for the half of it that is
 * about connecting to other people.
 */
export function InboxButton() {
  const colors = Colors[useScheme()];
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const inbox = useInbox(signedIn);
  const threads = useMessages(signedIn);

  // Summed rather than shown as two badges: the glyph leads to one
  // screen, so one number is the honest count of what is waiting
  // behind it.
  const unread =
    (inbox.data?.unread ?? 0) +
    (threads.data?.threads ?? []).reduce(
      (total, thread) => total + thread.unread,
      0,
    );

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={
        unread > 0 ? `Inbox, ${unread} unread` : 'Inbox'
      }
      animateEntrance={false}
      scale={0.92}
      onPress={() => router.push('/inbox')}
      style={{
        width: TapTarget,
        height: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <SymbolView
        name={{
          ios: 'bubble.left.and.bubble.right',
          android: 'forum',
          web: 'forum',
        }}
        size={24}
        tintColor={colors.text}
      />
      {unread > 0 ? (
        <View
          style={{
            position: 'absolute',
            top: 2,
            right: 0,
            minWidth: 18,
            height: 18,
            paddingHorizontal: Spacing.one,
            borderRadius: Radius.full,
            backgroundColor: colors.accent,
            alignItems: 'center',
            justifyContent: 'center',
            // A ring in the page colour, so the badge reads as sitting on
            // the glyph rather than merging with it at a glance.
            borderWidth: 2,
            borderColor: colors.background,
          }}>
          <ThemedText
            type="small"
            style={{
              fontSize: FontSize.meta,
              lineHeight: 14,
              color: colors.accentText,
              // Counters line up, and this one changes under the finger.
              fontVariant: ['tabular-nums'],
            }}>
            {unread > 9 ? '9+' : unread}
          </ThemedText>
        </View>
      ) : null}
    </MotionPressable>
  );
}
