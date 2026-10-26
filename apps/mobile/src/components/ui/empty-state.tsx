import { Pressable, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Colors, Fonts, Radius, Spacing } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

type Status = 'empty' | 'planned' | 'blocked' | 'error' | 'offline';

type EmptyStateProps = {
  /**
   * Which kind of nothing this is. The brief requires that a capability never
   * misrepresent its readiness, so the status is explicit rather than implied by
   * copy — `planned` and `blocked` render a visible label.
   */
  status: Status;
  title: string;
  /** Plain explanation. For `blocked`, say what would unblock it. */
  body: string;
  action?: { label: string; onPress: () => void };
};

const STATUS_LABEL: Record<Status, string | null> = {
  empty: null,
  planned: 'Not built yet',
  blocked: 'Needs setup',
  error: 'Something went wrong',
  offline: 'Offline',
};

/**
 * Honest empty, planned, blocked, error and offline states (§3, §22).
 *
 * One component for all five so a screen cannot accidentally present an
 * unimplemented feature as merely empty — the difference is the whole point.
 */
export function EmptyState({ status, title, body, action }: EmptyStateProps) {
  const colors = Colors[useScheme()];
  const label = STATUS_LABEL[status];

  return (
    <View
      // Announced as one unit so a screen reader does not read it as fragments.
      accessible
      accessibilityLabel={`${label ? `${label}. ` : ''}${title}. ${body}`}
      style={{
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.three,
        paddingVertical: Spacing.six,
        paddingHorizontal: Spacing.three,
      }}>
      {label ? (
        <View
          style={{
            paddingHorizontal: Spacing.two,
            paddingVertical: Spacing.half,
            borderRadius: Radius.full,
            borderWidth: 1,
            borderColor: status === 'error' ? colors.danger : colors.border,
          }}>
          <ThemedText
            type="small"
            style={{
              fontSize: 11,
              color: status === 'error' ? colors.danger : colors.textSecondary,
            }}>
            {label}
          </ThemedText>
        </View>
      ) : null}

      <ThemedText
        style={{
          fontFamily: Fonts.serif,
          fontSize: 24,
          lineHeight: 30,
          textAlign: 'center',
          color: colors.text,
        }}>
        {title}
      </ThemedText>

      <ThemedText
        type="small"
        themeColor="textSecondary"
        style={{ textAlign: 'center', maxWidth: 320 }}>
        {body}
      </ThemedText>

      {action ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={action.label}
          onPress={action.onPress}
          style={({ pressed }) => ({
            minHeight: 44,
            justifyContent: 'center',
            paddingHorizontal: Spacing.four,
            borderRadius: Radius.full,
            backgroundColor: colors.accent,
            opacity: pressed ? 0.8 : 1,
          })}>
          <ThemedText type="smallBold" style={{ color: colors.accentText }}>
            {action.label}
          </ThemedText>
        </Pressable>
      ) : null}
    </View>
  );
}
