import { useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Screen } from '@/components/ui/screen';
import {
  Colors,
  Radius,
  Spacing,
  labelType,
} from '@/constants/theme';
import {
  availableActions,
  detectPlatform,
  supportFor,
} from '@/features/social-import/platforms';
import { openSite } from '@/features/profile/website';
import { useScheme } from '@/hooks/use-theme';

/**
 * Add inspiration from a link (§11).
 *
 * Reached by pasting a URL or by sharing a post into the app from Instagram, TikTok
 * or another supported platform — `+native-intent.ts` routes
 * incoming shares here.
 *
 * The screen's job is to be truthful: it says what we can do with this particular
 * link, and when garment analysis is not permitted it offers the alternative that
 * works rather than failing or pretending.
 */
/**
 * Pull the shared link out of whatever the platform handed us.
 *
 * The share payload's shape is not fixed — it arrives as a query parameter
 * on an `expo-sharing` deep link, under a key that differs by platform and
 * by the app doing the sharing. Rather than guess at the key, take the first
 * http(s) link in the decoded payload: a share whose point is a post URL has
 * exactly one, and a payload with none yields an empty field, which is where
 * this screen started anyway.
 */
function sharedLink(payload: string | string[] | undefined): string {
  const raw = Array.isArray(payload) ? payload[0] : payload;
  if (!raw) return '';
  let decoded = raw;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    // A payload that is not valid percent-encoding is still worth scanning.
  }
  return /https?:\/\/[^\s"'<>]+/.exec(decoded)?.[0] ?? '';
}

export default function ImportScreen() {
  const colors = Colors[useScheme()];
  const { shared } = useLocalSearchParams<{ shared?: string }>();
  // Seeded once, in a lazy initialiser rather than an effect: setting state
  // from a prop inside an effect is both a lint error here and a second
  // render. The sheet is presented per share, so it mounts with the payload
  // it is for — a share arriving while it is already open keeps whatever is
  // typed, which is the right answer for anybody mid-edit.
  const [url, setUrl] = useState(() => sharedLink(shared));

  const trimmed = url.trim();
  const support = useMemo(
    () => (trimmed ? supportFor(detectPlatform(trimmed)) : null),
    [trimmed],
  );
  const actions = support ? availableActions(support) : [];

  return (
    <Screen scroll>
      <View style={{ gap: Spacing.two, marginBottom: Spacing.four }}>
        <ThemedText style={{ ...labelType(28, 800), lineHeight: 34 }}>
          Add inspiration
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Paste a link to a post, or share one into the app. You can also add your own
          photo.
        </ThemedText>
      </View>

      <TextInput
        value={url}
        onChangeText={setUrl}
        placeholder="https://www.instagram.com/p/…"
        placeholderTextColor={colors.textSecondary}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        inputMode="url"
        accessibilityLabel="Post link"
        style={{
          minHeight: 48,
          paddingHorizontal: Spacing.three,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          borderWidth: 1,
          borderColor: colors.border,
          backgroundColor: colors.backgroundElement,
          color: colors.text,
          fontSize: 16,
        }}
      />

      {support ? (
        <View style={{ marginTop: Spacing.four, gap: Spacing.three }}>
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.two,
            }}>
            <ThemedText type="smallBold">{support.label}</ThemedText>
            <CapabilityChip
              ok={support.capability.canAnalyse}
              label={
                support.capability.canAnalyse
                  ? 'Can identify garments'
                  : 'Link only'
              }
            />
          </View>

          {support.limitation ? (
            <View
              style={{
                padding: Spacing.three,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                borderWidth: 1,
                borderColor: colors.border,
                gap: Spacing.two,
              }}>
              <ThemedText type="small" themeColor="textSecondary">
                {support.limitation}
              </ThemedText>
            </View>
          ) : null}

          <View style={{ gap: Spacing.two }}>
            {actions.map((action) => (
              <ActionRow
                key={action}
                label={action}
                onPress={
                  action === 'Open original post'
                    ? () => openSite(trimmed)
                    : undefined
                }
              />
            ))}
          </View>

          {/* Always offered, because it is the path that always works. */}
          <ActionRow label="Add a photo or screenshot instead" emphasis />
        </View>
      ) : null}
    </Screen>
  );
}

function CapabilityChip({ ok, label }: { ok: boolean; label: string }) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        paddingHorizontal: Spacing.two,
        paddingVertical: Spacing.half,
        borderRadius: Radius.full,
        borderWidth: 1,
        borderColor: ok ? colors.accent : colors.border,
      }}>
      <ThemedText
        type="small"
        style={{ fontSize: 11, color: ok ? colors.accent : colors.textSecondary }}>
        {label}
      </ThemedText>
    </View>
  );
}

function ActionRow({
  label,
  onPress,
  emphasis,
}: {
  label: string;
  onPress?: () => void;
  emphasis?: boolean;
}) {
  const colors = Colors[useScheme()];
  // Actions whose backend has not landed are shown but not pressable, rather than
  // silently absent — the user can see what this link will support.
  const disabled = !onPress && !emphasis;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 48,
        paddingHorizontal: Spacing.three,
        justifyContent: 'center',
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: emphasis ? colors.accent : colors.backgroundElement,
        opacity: disabled ? 0.45 : pressed ? 0.75 : 1,
      })}>
      <ThemedText
        type="small"
        style={{ color: emphasis ? colors.accentText : colors.text }}>
        {label}
      </ThemedText>
    </Pressable>
  );
}
