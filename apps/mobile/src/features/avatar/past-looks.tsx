import { Image } from 'expo-image';
import { useState } from 'react';
import { Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Render } from '@/api/queries/avatar';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  labelType,
} from '@/constants/theme';
import { PictureActions } from '@/features/avatar/picture-actions';
import { useScheme } from '@/hooks/use-theme';

/**
 * Looks drawn before this one.
 *
 * **A render used to vanish when the next question was asked.** It is
 * a billed picture somebody waited half a minute for, and the only
 * copy was on screen until it was not. The server has kept every one
 * all along - `useRenders` already lists them - so the fix was to
 * show the list rather than to store anything new.
 *
 * Tapping one opens it full size with the same save, share and post
 * row the fresh one has: an old look is not a lesser picture.
 */

/** How many to keep on the strip. Beyond this it is an archive, not a recall. */
const SHOWN = 12;

/**
 * The finished try-ons, newest first, minus the one already on screen.
 *
 * Exported because "which of these is worth showing" is the rule: a
 * base avatar is not a look, a failed render is not a picture, and
 * the one above the strip must not also be in it.
 */
export function pastLooks(
  renders: readonly Render[],
  skip: string | null,
): Render[] {
  return renders
    .filter(
      (render) =>
        render.kind === 'try_on' &&
        render.state === 'ready' &&
        render.uri !== null &&
        render.id !== skip,
    )
    .slice(0, SHOWN);
}

export function PastLooks({
  renders,
  skip,
}: {
  renders: readonly Render[];
  /** The render shown above the strip, so it is not repeated in it. */
  skip: string | null;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState<Render | null>(null);

  const looks = pastLooks(renders, skip);
  if (looks.length === 0) return null;

  return (
    <View style={{ gap: Spacing.two }}>
      <ThemedText accessibilityRole="header" style={labelType(FontSize.meta, 800)}>
        Looks you have tried
      </ThemedText>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ flexDirection: 'row', gap: Spacing.two }}>
        {looks.map((look) => (
          <MotionPressable
            key={look.id}
            accessibilityRole="button"
            accessibilityLabel={look.outfit ?? 'A look you tried'}
            accessibilityHint="Opens it full size"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              setOpen(look);
            }}
            style={{
              width: 84,
              aspectRatio: 3 / 4,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              overflow: 'hidden',
              backgroundColor: colors.backgroundElement,
            }}>
            <Image
              source={{ uri: look.uri as string }}
              contentFit="cover"
              transition={ImageFade}
              style={{ width: '100%', height: '100%' }}
            />
          </MotionPressable>
        ))}
      </ScrollView>

      <Modal
        visible={open !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(null)}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close"
          onPress={() => setOpen(null)}
          style={{
            flex: 1,
            justifyContent: 'center',
            padding: Spacing.three,
            paddingBottom: insets.bottom + Spacing.three,
            // Near-opaque. At 80% the page behind read straight
            // through and every label on top of it had two
            // backgrounds to fight.
            backgroundColor: '#000000F5',
          }}>
          {/* Swallows taps so pressing the sheet does not close it. */}
          <Pressable onPress={() => {}} style={{ gap: Spacing.three }}>
            {open?.uri ? (
              <Image
                source={{ uri: open.uri }}
                // The whole figure, head to foot. Filling the frame
                // takes off the two things somebody is checking.
                contentFit="contain"
                transition={ImageFade}
                style={{
                  width: '100%',
                  aspectRatio: 3 / 4,
                  borderRadius: Radius.lg,
                }}
              />
            ) : null}
            {open?.outfit ? (
              <ThemedText
                selectable
                style={{ ...labelType(FontSize.subhead, 400), color: '#FFFFFF' }}>
                {open.outfit}
              </ThemedText>
            ) : null}
            <PictureActions
              uri={open?.uri ?? null}
              on="dark"
              onLeave={() => setOpen(null)}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
