import { Modal, Pressable, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Colors, Radius, Spacing, TapTarget } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * The five faces, on a hold.
 *
 * A row rather than a menu: they are one tap each and a list would make
 * choosing between five emoji feel like a settings screen.
 */
export function ReactionPicker({
  visible,
  kinds,
  chosen,
  onClose,
  onPick,
}: {
  visible: boolean;
  kinds: readonly { kind: string; emoji: string }[];
  chosen: string | null;
  onClose: () => void;
  onPick: (kind: string) => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close"
        onPress={onClose}
        style={{
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: '#00000059',
          padding: Spacing.four,
        }}>
        <View
          style={{
            flexDirection: 'row',
            gap: Spacing.one,
            padding: Spacing.two,
            borderRadius: Radius.full,
            backgroundColor: colors.background,
            boxShadow: '0 8px 24px rgba(0, 0, 0, 0.22)',
          }}>
          {kinds.map((kind) => (
            <MotionPressable
              key={kind.kind}
              accessibilityRole="button"
              accessibilityLabel={kind.kind}
              accessibilityState={{ selected: chosen === kind.kind }}
              animateEntrance={false}
              scale={0.85}
              onPress={() => {
                void tapFeedback();
                onPick(kind.kind);
              }}
              style={{
                width: TapTarget,
                height: TapTarget,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: Radius.full,
                backgroundColor:
                  chosen === kind.kind ? colors.backgroundSelected : 'transparent',
              }}>
              <ThemedText style={{ fontSize: 26 }}>{kind.emoji}</ThemedText>
            </MotionPressable>
          ))}
        </View>
      </Pressable>
    </Modal>
  );
}
