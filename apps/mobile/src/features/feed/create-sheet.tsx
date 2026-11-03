import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * What the `+` offers: three things to make.
 *
 * **A sheet, not a screen.** Choosing what kind of thing to make is a
 * decision taken in half a second, and routing to a page to ask it
 * puts a navigation step in front of every post.
 *
 * **Pin goes straight to the camera roll.** A pin *is* a photograph -
 * it is the thing on the Discover grid - so the first question is
 * "which picture", not "which look from our catalogue". The composer
 * opens afterwards with the photograph already on it.
 */
export function CreateSheet({
  visible,
  onClose,
  onPin,
}: {
  visible: boolean;
  onClose: () => void;
  /** Opens the photo library, then the composer. */
  onPin: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close"
        onPress={onClose}
        style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000066' }}>
        <Pressable
          // Swallows taps so pressing the sheet does not close it.
          onPress={() => {}}
          style={{
            paddingTop: Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingBottom: insets.bottom + Spacing.four,
            gap: Spacing.four,
            backgroundColor: colors.background,
            borderTopLeftRadius: Radius.lg,
            borderTopRightRadius: Radius.lg,
            borderCurve: 'continuous',
          }}>
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.two,
            }}>
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel="Close"
              animateEntrance={false}
              scale={0.9}
              hitSlop={8}
              onPress={() => {
                void tapFeedback();
                onClose();
              }}>
              <SymbolView
                name={{ ios: 'xmark', android: 'close', web: 'close' }}
                size={16}
                tintColor={colors.text}
              />
            </MotionPressable>
            <ThemedText
              accessibilityRole="header"
              type="smallBold"
              style={{ flex: 1, textAlign: 'center' }}>
              Start creating
            </ThemedText>
            {/* Balances the close button so the title sits centred. */}
            <View style={{ width: 16 }} />
          </View>

          <View
            style={{
              flexDirection: 'row',
              justifyContent: 'center',
              gap: Spacing.three,
            }}>
            <Door
              label="Pin"
              hint="Post a photograph from your phone"
              icon={{ ios: 'pin', android: 'push_pin', web: 'push_pin' }}
              onPress={() => {
                onClose();
                onPin();
              }}
            />
            <Door
              label="Collage"
              hint="Cut pictures together into one"
              icon={{
                ios: 'square.on.square.dashed',
                android: 'auto_awesome_mosaic',
                web: 'auto_awesome_mosaic',
              }}
              onPress={() => {
                onClose();
                router.push('/collage');
              }}
            />
            <Door
              label="Board"
              hint="A place to collect fits"
              icon={{
                ios: 'rectangle.split.2x1',
                android: 'dashboard',
                web: 'dashboard',
              }}
              onPress={() => {
                onClose();
                router.push('/moodboards');
              }}
            />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** One thing you can make: a glyph in a tile, with its name under it. */
function Door({
  label,
  hint,
  icon,
  onPress,
}: {
  label: string;
  hint: string;
  icon: SymbolViewProps['name'];
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      animateEntrance={false}
      scale={0.95}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{ alignItems: 'center', gap: Spacing.one }}>
      <View
        style={{
          width: TapTarget + Spacing.five,
          height: TapTarget + Spacing.five,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
        }}>
        <SymbolView name={icon} size={26} tintColor={colors.text} />
      </View>
      <ThemedText type="small" style={{ fontSize: FontSize.footnote }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
