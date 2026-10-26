import { EmptyState } from '@/components/ui/empty-state';
import { Screen } from '@/components/ui/screen';
import { ThemedText } from '@/components/themed-text';
import { Fonts, Spacing } from '@/constants/theme';
import { View } from 'react-native';

/**
 * Wardrobe — the user's own items, filters, collections and capture (§3, §5).
 *
 * Empty until capture and the wardrobe API land (plan Tasks 5 and 13). The state is
 * labelled `empty` rather than `planned` because the screen itself works; it is the
 * user's wardrobe that has nothing in it yet.
 */
export default function WardrobeScreen() {
  return (
    <Screen scroll>
      <View style={{ gap: Spacing.one, marginBottom: Spacing.three }}>
        <ThemedText style={{ fontFamily: Fonts.serif, fontSize: 40, lineHeight: 44 }}>
          Wardrobe
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Private to you. Nothing here is published unless you choose to.
        </ThemedText>
      </View>

      <EmptyState
        status="empty"
        title="Your wardrobe is empty"
        body="Photograph a garment, or load a sample wardrobe to try styling straight away. Capture arrives with the wardrobe API — the screen and its grid are ready for it."
      />
    </Screen>
  );
}
