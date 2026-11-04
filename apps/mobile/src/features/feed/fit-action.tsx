import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Colors, FontSize, Spacing, labelType } from '@/constants/theme';
import { compactCount } from '@/features/feed/counts';
import { useScheme } from '@/hooks/use-theme';

/**
 * One of the three things you do to a fit: react, read it, send it.
 *
 * **One component because they are one set.** They sat in two files with
 * their own sizes and their own gaps - the heart and the share glyph
 * here, the bubble over in `comments` - and drifted apart, which is
 * visible: a row of controls that do not match reads as three controls
 * rather than as a row.
 *
 * **Outlined, at the reference's stroke.** The weight is set rather
 * than left to the system, so the three match each other. `light` was
 * a half-step too thin: beside the reference the glyphs read as
 * spindly, and the share tray in particular lost its shape. `regular`
 * is the line the reference draws.
 */

/** The look of every action glyph. Set in one place so they match. */
export const ActionIcon = { size: 26, weight: 'regular' } as const;

/**
 * Width held for a tally, whether or not there is one yet.
 *
 * **The row must not move when the counts arrive.** They are fetched
 * with the fit, so for the first moment of every pin there are none,
 * and the slot used to collapse: the share glyph sat left of where it
 * was about to end up and jumped right the instant a comment count
 * landed. Two posts side by side had their controls in different
 * places for the same reason, one having been commented on and the
 * other not.
 *
 * **Four characters, which is every tally this app can print.**
 * `compactCount` never returns more: `999` is the longest plain
 * number and `1.2K` the longest short form. Sized for the widest
 * possible value, the row cannot move at any count - which was the
 * remaining complaint after the slot was first reserved at two
 * characters and a three-digit tally still nudged everything along.
 *
 * At `FontSize.footnote` a tabular digit is about six points, so
 * four of them and a little air is 26. Smaller type is what makes
 * reserving the whole range affordable: at the old body size the
 * same guarantee would have cost 38 points of empty space under
 * every photograph.
 */
export const COUNT_SLOT = 26;

/**
 * What one action occupies with its tally slot.
 *
 * Exported so the skeleton can be drawn at the width the real thing
 * will take. Hard-coded placeholder widths are how a skeleton comes
 * to be a different shape from what replaces it.
 */
export const ACTION_WIDTH = ActionIcon.size + Spacing.two + COUNT_SLOT;

export function FitAction({
  label,
  hint,
  icon,
  emoji,
  count,
  tint,
  onPress,
  onLongPress,
}: {
  label: string;
  hint?: string;
  icon: SymbolViewProps['name'];
  /** Their own reaction, shown in place of the glyph once they have left one. */
  emoji?: string;
  /**
   * The tally beside it, when there is one to show.
   *
   * Omitted entirely at zero rather than drawn as "0": a nought under
   * somebody's photograph reads as a verdict on it, and the reference
   * shows a bare glyph until there is something to count.
   */
  count?: number;
  tint?: string;
  onPress: () => void;
  onLongPress?: () => void;
}) {
  const colors = Colors[useScheme()];
  const shown = count && count > 0 ? compactCount(count) : null;

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={shown ? `${label}. ${shown} so far.` : label}
      accessibilityHint={hint}
      animateEntrance={false}
      scale={0.9}
      hitSlop={8}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      onLongPress={
        onLongPress
          ? () => {
              void tapFeedback();
              onLongPress();
            }
          : undefined
      }
      style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.two }}>
      {/* **The glyph gets its own box, the tally gets its own box.**

          The tally already had a reserved slot, and things still
          moved when somebody reacted - because reacting swaps the
          symbol for an emoji, and an emoji's advance width is not
          the symbol's. The row was laid out from whatever was
          currently in it, so liking a pin nudged the count, then the
          comment control, then everything after it.

          A fixed square holds both states at the same size, so the
          swap happens inside the box and nothing outside it is
          affected. Two shells, each a known width: that is what
          makes the row still. */}
      <View
        style={{
          width: ActionIcon.size,
          height: ActionIcon.size,
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        {emoji ? (
          <ThemedText style={{ fontSize: ActionIcon.size - 6 }}>
            {emoji}
          </ThemedText>
        ) : (
          <SymbolView
            name={icon}
            size={ActionIcon.size}
            weight={ActionIcon.weight}
            tintColor={tint ?? colors.text}
          />
        )}
      </View>
      {/* Always rendered, never conditional, and a fixed width
          whether it holds a number or nothing. */}
      <ThemedText
        style={{
          // **Small, beside the glyph rather than competing with
          // it.** It was body size at the heaviest weight, which
          // made a tally of four read as loudly as the caption
          // underneath. The reference sets it a size down and at a
          // normal weight: the number is an annotation on the
          // control, not a headline.
          ...labelType(FontSize.footnote, 400),
          fontVariant: ['tabular-nums'],
          // A fixed width, not a minimum: `minWidth` still grows past
          // 26 for a five-digit tally, and a pin that crosses ten
          // thousand would start nudging the row again.
          width: COUNT_SLOT,
        }}>
        {shown ?? ''}
      </ThemedText>
    </MotionPressable>
  );
}
