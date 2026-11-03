import { Pressable, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Collage, type CollageFrame } from '@/components/ui/collage';
import {
  Colors,
  Radius,
  Spacing,
  labelType,
} from '@/constants/theme';
import { EMPTY_STAGE } from '@/features/discover/sheets';
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
  /**
   * A pile of prints above the heading, saying what the screen is for by
   * showing it rather than describing it.
   *
   * **Ignored unless `status` is `empty`.** A failure, an offline state or
   * something not built yet has to look like what it is; dressing one up is
   * how a broken screen gets mistaken for a working one, and the brief
   * requires that a capability never misrepresent its readiness.
   */
  sheet?: readonly CollageFrame[];
  /** Stage proportion for the sheet. Defaults to the shallow empty-state one. */
  sheetAspectRatio?: number;
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
export function EmptyState({
  status,
  title,
  body,
  action,
  sheet,
  sheetAspectRatio = EMPTY_STAGE,
}: EmptyStateProps) {
  const colors = Colors[useScheme()];
  const label = STATUS_LABEL[status];
  const showSheet = status === 'empty' && sheet && sheet.length > 0;

  return (
    <View
      style={{
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.three,
        paddingVertical: Spacing.six,
        paddingHorizontal: Spacing.three,
      }}>
      {/* Outside the `accessible` grouping above would be ideal, but the
          wrapper owns the label; the cards set `accessible={false}` through
          `Collage`'s own alt handling, and the grouped label already names
          what this screen is. */}
      {showSheet ? (
        <View style={{ width: '100%' }}>
          <Collage frames={sheet} aspectRatio={sheetAspectRatio} />
        </View>
      ) : null}

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

      {/* The text is announced as one unit; the button is not inside it.
          This wrapper used to be the whole component, with `accessible` on
          it — which collapses every descendant into a single element and
          made the action unreachable to a screen reader. An empty state
          whose only way forward cannot be focused is worse than one with no
          button at all. */}
      <View
        accessible
        accessibilityLabel={`${label ? `${label}. ` : ''}${title}. ${body}`}
        style={{ alignItems: 'center', gap: Spacing.three }}>
        <ThemedText
          style={{
            ...labelType(24, 800),
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
      </View>

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
