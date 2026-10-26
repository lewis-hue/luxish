import * as WebBrowser from 'expo-web-browser';
import { Pressable, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Screen } from '@/components/ui/screen';
import { BRAND } from '@/branding';
import { Colors, Fonts, Radius, Spacing } from '@/constants/theme';
import {
  CHATGPT_STATE_COPY,
  type ChatGptConnectionState,
} from '@/features/account/chatgpt-connection';
import { useScheme } from '@/hooks/use-theme';

/**
 * Profile — saved collections, preferences, subscriptions, connections, privacy and
 * creator tools (§3).
 *
 * The rows that exist today are the ones that can tell the truth today: legal and
 * support links, and the AI connection state. Everything else states its phase
 * rather than opening a dead screen.
 */
export default function ProfileScreen() {
  const colors = Colors[useScheme()];

  // Ships `unavailable`: commercial Sign in with ChatGPT is waitlist-gated, so no
  // other state is reachable yet (ADR-008).
  const chatGptState: ChatGptConnectionState = 'unavailable';

  const open = (url: string) => WebBrowser.openBrowserAsync(url);

  return (
    <Screen scroll>
      <View style={{ gap: Spacing.one, marginBottom: Spacing.four }}>
        <ThemedText style={{ fontFamily: Fonts.serif, fontSize: 40, lineHeight: 44 }}>
          Profile
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Not signed in. Browsing works without an account.
        </ThemedText>
      </View>

      <Section title="AI">
        <Row
          label="ChatGPT connection"
          value={CHATGPT_STATE_COPY[chatGptState].short}
          detail={CHATGPT_STATE_COPY[chatGptState].detail}
        />
        <Row
          label="AI allowance"
          value="Free tier"
          detail="A capped, app-funded allowance. Paid plans and any ChatGPT-plan connection are billed separately and never switched without asking you."
        />
      </Section>

      <Section title="Privacy">
        <Row
          label="Wardrobe visibility"
          value="Private"
          detail="Your wardrobe and conversations are private by default. Publishing to the community is always a separate, explicit action."
        />
        <Row
          label="Training consent"
          value="Off"
          detail="Your photos, conversations and precise location are excluded from model training by default."
        />
        <Row
          label="Location"
          value="Not shared"
          detail="Styling works from a city you type in. Device location is only requested when you ask for local weather or nearby shops."
        />
      </Section>

      <Section title="Account">
        <LinkRow label="Delete account" onPress={() => open(BRAND.urls.accountDeletion)} />
        <LinkRow label="Export my data" phase="Phase D" />
        <LinkRow label="Creator tools" phase="Phase D" />
        <LinkRow label="Subscriptions" phase="Phase D" />
      </Section>

      <Section title="About">
        <LinkRow label="Privacy policy" onPress={() => open(BRAND.urls.privacy)} />
        <LinkRow label="Terms" onPress={() => open(BRAND.urls.terms)} />
        <LinkRow label="Content policy" onPress={() => open(BRAND.urls.contentPolicy)} />
        <LinkRow label="Support" onPress={() => open(BRAND.support.url)} />
      </Section>

      {BRAND.isWorkingName ? (
        <View
          style={{
            marginTop: Spacing.four,
            padding: Spacing.three,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.border,
          }}>
          <ThemedText type="small" themeColor="textSecondary">
            {BRAND.name} is a working name. Branding is centralised, so the final name
            replaces it in one place.
          </ThemedText>
        </View>
      ) : null}
    </Screen>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const colors = Colors[useScheme()];
  return (
    <View style={{ marginBottom: Spacing.four, gap: Spacing.two }}>
      <ThemedText
        type="small"
        themeColor="textSecondary"
        // Grouped-list section header, the platform idiom — not a card.
        style={{ textTransform: 'uppercase', letterSpacing: 0.6, fontSize: 12 }}>
        {title}
      </ThemedText>
      <View
        style={{
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
          overflow: 'hidden',
        }}>
        {children}
      </View>
    </View>
  );
}

function Row({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        padding: Spacing.three,
        gap: Spacing.one,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
      }}>
      <View
        style={{
          flexDirection: 'row',
          justifyContent: 'space-between',
          gap: Spacing.two,
        }}>
        <ThemedText type="small">{label}</ThemedText>
        <ThemedText type="smallBold" style={{ color: colors.accent }}>
          {value}
        </ThemedText>
      </View>
      <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 13 }}>
        {detail}
      </ThemedText>
    </View>
  );
}

function LinkRow({
  label,
  onPress,
  phase,
}: {
  label: string;
  onPress?: () => void;
  phase?: string;
}) {
  const colors = Colors[useScheme()];
  const disabled = !onPress;
  return (
    <Pressable
      accessibilityRole={disabled ? 'text' : 'link'}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 48,
        paddingHorizontal: Spacing.three,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: Spacing.two,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
        opacity: pressed ? 0.6 : 1,
      })}>
      <ThemedText type="small" themeColor={disabled ? 'textSecondary' : 'text'}>
        {label}
      </ThemedText>
      {/* States its phase instead of opening an empty screen. */}
      <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 12 }}>
        {phase ?? '›'}
      </ThemedText>
    </Pressable>
  );
}
