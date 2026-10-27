import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { Screen } from '@/components/ui/screen';
import { Display, Spacing } from '@/constants/theme';

/**
 * Stylist — conversations, outfit generation and saved plans (§3, §6).
 *
 * `blocked`, not `planned`: the agent loop, prompts and tool contracts are specified
 * and the provider adapter is written, but a Meta Model API key has not been issued,
 * so no real run can execute. Saying "not built yet" here would be inaccurate.
 */
export default function StylistScreen() {
  return (
    <Screen scroll>
      <View style={{ gap: Spacing.one, marginBottom: Spacing.three }}>
        <ThemedText style={{ fontFamily: Display.regular, fontSize: 40, lineHeight: 44 }}>
          Stylist
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Outfits from the clothes you already own.
        </ThemedText>
      </View>

      <EmptyState
        status="blocked"
        title="Styling needs an AI key"
        body="The stylist runs on the Meta Model API. Add a MODEL_API_KEY to the backend and this becomes live — no app change needed. Until then nothing here is simulated."
      />
    </Screen>
  );
}
