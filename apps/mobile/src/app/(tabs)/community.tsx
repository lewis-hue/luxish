import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { Screen } from '@/components/ui/screen';
import { Display, Spacing } from '@/constants/theme';

/**
 * Community — discovery and following feeds, creator content, posting (§3, §12).
 *
 * Phase C. Labelled `planned` so it cannot read as an empty feed.
 */
export default function CommunityScreen() {
  return (
    <Screen scroll>
      <View style={{ gap: Spacing.one, marginBottom: Spacing.three }}>
        <ThemedText style={{ fontFamily: Display.regular, fontSize: 40, lineHeight: 44 }}>
          Community
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Looks from people you follow.
        </ThemedText>
      </View>

      <EmptyState
        status="planned"
        title="Community opens in Phase C"
        body="Posts, short video, comments, saves, follows, creator profiles and item search from a post are specified and scheduled. Moderation has to ship with them, not after, so the whole surface lands together."
      />
    </Screen>
  );
}
