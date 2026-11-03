import { Image } from 'expo-image';
import { useEffect } from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/** How long it stands before it goes. Long enough to read and reach. */
const LINGER_MS = 5000;

/**
 * What just happened, and the one thing to do about it.
 *
 * **Saving is the app's most-pressed button and it used to say
 * nothing.** The picture was kept, the control changed one word, and
 * where it went was somewhere you had to go looking. This says where.
 *
 * **"Organise" is an offer, not a question.** The save already
 * happened — this is not a dialog asking which board, which would make
 * every save a two-step decision. Sorting it is available for the few
 * seconds somebody is still thinking about the picture, and ignoring
 * it is the normal case.
 *
 * **It leaves on its own and it is reachable while it is here.** A
 * notice that waits for a dismissal is a thing to dismiss; one that
 * cannot be acted on is decoration.
 */
export function SavedNote({
  visible,
  where,
  uri,
  onOrganise,
  onDone,
}: {
  visible: boolean;
  /** Where it landed, in the words the destination uses. */
  where: string;
  /** The picture that was saved, so the note is about something. */
  uri?: string | null;
  onOrganise: () => void;
  onDone: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();

  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(onDone, LINGER_MS);
    return () => clearTimeout(timer);
  }, [visible, onDone]);

  if (!visible) return null;

  return (
    <View
      // Over the picture, not in the layout: the page underneath must
      // not jump by the height of a notice that is about to leave.
      pointerEvents="box-none"
      accessibilityLiveRegion="polite"
      style={{
        position: 'absolute',
        top: insets.top + Spacing.one,
        left: Spacing.two,
        right: Spacing.two,
      }}>
      <View
        accessible
        accessibilityLabel={`Saved to ${where}`}
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
          padding: Spacing.one,
          paddingLeft: Spacing.two,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: colors.text,
          boxShadow: '0 6px 20px rgba(0, 0, 0, 0.28)',
        }}>
        {uri ? (
          <Image
            source={{ uri }}
            contentFit="cover"
            accessible={false}
            style={{
              width: 36,
              height: 36,
              borderRadius: Radius.sm,
              borderCurve: 'continuous',
            }}
          />
        ) : null}
        <ThemedText
          numberOfLines={1}
          style={{
            flex: 1,
            ...labelType(FontSize.body, 800),
            color: colors.background,
          }}>
          Saved to {where}
        </ThemedText>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Organise this save into a board"
          animateEntrance={false}
          scale={0.96}
          onPress={() => {
            void tapFeedback();
            onOrganise();
            onDone();
          }}
          style={{
            minHeight: TapTarget - Spacing.one,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.background,
          }}>
          <ThemedText style={labelType(FontSize.subhead, 800)}>
            Organise
          </ThemedText>
        </MotionPressable>
      </View>
    </View>
  );
}
