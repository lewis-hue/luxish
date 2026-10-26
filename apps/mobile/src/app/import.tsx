import * as WebBrowser from 'expo-web-browser';
import { useMemo, useState } from 'react';
import { Pressable, TextInput, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Screen } from '@/components/ui/screen';
import { Colors, Fonts, Radius, Spacing } from '@/constants/theme';
import {
  availableActions,
  detectPlatform,
  supportFor,
} from '@/features/social-import/platforms';
import { useScheme } from '@/hooks/use-theme';

/**
 * Add inspiration from a link (§11).
 *
 * Reached by pasting a URL or by sharing a post into the app from Instagram, TikTok
 * or Pinterest — `+native-intent.ts` routes incoming shares here.
 *
 * The screen's job is to be truthful: it says what we can do with this particular
 * link, and when garment analysis is not permitted it offers the alternative that
 * works rather than failing or pretending.
 */
export default function ImportScreen() {
  const colors = Colors[useScheme()];
  const [url, setUrl] = useState('');

  const trimmed = url.trim();
  const support = useMemo(
    () => (trimmed ? supportFor(detectPlatform(trimmed)) : null),
    [trimmed],
  );
  const actions = support ? availableActions(support) : [];

  return (
    <Screen scroll>
      <View style={{ gap: Spacing.two, marginBottom: Spacing.four }}>
        <ThemedText style={{ fontFamily: Fonts.serif, fontSize: 28, lineHeight: 34 }}>
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
                    ? () => WebBrowser.openBrowserAsync(trimmed)
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
