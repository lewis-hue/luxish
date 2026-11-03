import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { Modal, View, useWindowDimensions } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { useSharedValue } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Colors, ImageFade, Radius, Spacing, TapTarget } from '@/constants/theme';
import { Zoomable } from '@/features/feed/zoomable';
import { useScheme } from '@/hooks/use-theme';

/**
 * One picture, the size of the screen, with a way to look closer.
 *
 * **For pictures that are not fits.** A fit has its own full-screen
 * view with a shelf of related pins under it, which is right for a
 * pin and wrong for a photograph somebody sent in a message: there
 * is nothing related to show, and the sheet would be an empty
 * drawer over their picture.
 *
 * A picture in a message bubble is 220pt wide. Whatever was being
 * pointed at - a label, a seam, a pair of shoes - was not legible
 * at that size and there was no way to make it bigger, which made
 * sending a photograph a worse way to show somebody something than
 * describing it.
 */
export function ImageViewer({
  uri,
  visible,
  label,
  onClose,
}: {
  uri: string | null;
  visible: boolean;
  /** What a screen reader should call it. */
  label?: string;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const zoom = useSharedValue(1);

  return (
    <Modal
      visible={visible}
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent>
      <GestureHandlerRootView style={{ flex: 1 }}>
        <View style={{ flex: 1, backgroundColor: colors.backgroundElement }}>
          {uri ? (
            <Zoomable
              scale={zoom}
              width={width}
              height={height}
              style={{ position: 'absolute', width, height }}>
              <Image
                source={{ uri }}
                // The whole picture, because here there is room for
                // it. The bubble crops to a tidy shape; this is the
                // screen somebody opened to see what was cropped.
                contentFit="contain"
                transition={ImageFade}
                cachePolicy="memory-disk"
                priority="high"
                accessible
                accessibilityLabel={label ?? 'A picture'}
                style={{ width: '100%', height: '100%' }}
              />
            </Zoomable>
          ) : null}

          <View
            style={{
              position: 'absolute',
              top: insets.top + Spacing.two,
              left: Spacing.three,
            }}>
            <View
              accessible
              accessibilityRole="button"
              accessibilityLabel="Close"
              onTouchEnd={onClose}
              style={{
                width: TapTarget,
                height: TapTarget,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: Radius.full,
                backgroundColor: colors.background,
              }}>
              <SymbolView
                name={{ ios: 'xmark', android: 'close', web: 'close' }}
                size={18}
                weight="semibold"
                tintColor={colors.text}
              />
            </View>
          </View>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}
