import { Image } from 'expo-image';
import { Pressable, View, type StyleProp, type ViewStyle } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { AspectRatio, Colors, Fonts, Motion, Radius, Spacing } from '@/constants/theme';
import { attributionLine, type InspirationAsset } from '@/features/discover/types';
import { useScheme } from '@/hooks/use-theme';

type StyleTileProps = {
  /** Null until an inspiration image source is licensed; falls back to type. */
  asset: InspirationAsset | null;
  title: string;
  subtitle?: string | null;
  /** Shown under the title, e.g. '24 looks'. */
  meta?: string | null;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
};

/**
 * Image-led tile for the Discover grid.
 *
 * Fixed aspect ratio (§3) so the grid never reflows as images land, a blurhash
 * placeholder so it never flashes empty, and two overlays that are not optional: the
 * licence attribution when the provider requires it, and an AI-generated disclosure
 * when the image came from a model (required by Google Play policy).
 *
 * With no asset it renders an editorial typographic cover rather than a grey box, so
 * the grid is complete before any imagery is licensed.
 */
export function StyleTile({
  asset,
  title,
  subtitle,
  meta,
  onPress,
  style,
}: StyleTileProps) {
  const colors = Colors[useScheme()];
  const credit = asset ? attributionLine(asset.source) : null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}${subtitle ? `. ${subtitle}` : ''}`}
      accessibilityHint="Opens this style collection"
      onPress={onPress}
      style={({ pressed }) => [
        {
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
          borderWidth: 1,
          borderColor: colors.border,
          opacity: pressed ? 0.88 : 1,
        },
        style,
      ]}>
      {asset ? (
        <Image
          source={{ uri: asset.uri }}
          placeholder={asset.blurhash ? { blurhash: asset.blurhash } : undefined}
          // 'memory-disk' is what keeps scrolling smooth on mid-range Android.
          cachePolicy="memory-disk"
          contentFit="cover"
          transition={Motion.base}
          accessible={false}
          style={{ width: '100%', aspectRatio: AspectRatio.editorial }}
        />
      ) : (
        <TypographicCover title={title} />
      )}

      {/* Label band, so text never sits directly on photography. */}
      <View style={{ padding: Spacing.three, gap: Spacing.one }}>
        <ThemedText type="smallBold" numberOfLines={1}>
          {title}
        </ThemedText>
        {subtitle ? (
          <ThemedText type="small" themeColor="textSecondary" numberOfLines={2}>
            {subtitle}
          </ThemedText>
        ) : null}

        {meta || asset?.isGenerated || credit ? (
          <View
            style={{
              flexDirection: 'row',
              gap: Spacing.two,
              flexWrap: 'wrap',
              marginTop: Spacing.one,
            }}>
            {meta ? <Badge label={meta} tone="muted" /> : null}
            {/* Disclosure, not decoration — never drop this for space. */}
            {asset?.isGenerated ? <Badge label="AI image" tone="accent" /> : null}
            {credit ? <Badge label={credit} tone="muted" /> : null}
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

/**
 * Editorial fallback cover: the category initial set large in the serif face, on the
 * raised surface. Reads as a deliberate design choice rather than a missing image.
 */
function TypographicCover({ title }: { title: string }) {
  const colors = Colors[useScheme()];
  return (
    <View
      accessible={false}
      style={{
        width: '100%',
        aspectRatio: AspectRatio.editorial,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.backgroundSelected,
      }}>
      <ThemedText
        style={{
          fontFamily: Fonts.serif,
          fontSize: 72,
          lineHeight: 80,
          color: colors.accent,
        }}>
        {title.trim().charAt(0).toUpperCase()}
      </ThemedText>
    </View>
  );
}

function Badge({ label, tone }: { label: string; tone: 'accent' | 'muted' }) {
  const colors = Colors[useScheme()];
  const accent = tone === 'accent';
  return (
    <View
      style={{
        paddingHorizontal: Spacing.two,
        paddingVertical: Spacing.half,
        borderRadius: Radius.full,
        backgroundColor: accent ? colors.accent : 'transparent',
        borderWidth: accent ? 0 : 1,
        borderColor: colors.border,
      }}>
      <ThemedText
        type="small"
        style={{
          fontSize: 11,
          color: accent ? colors.accentText : colors.textSecondary,
        }}
        numberOfLines={1}>
        {label}
      </ThemedText>
    </View>
  );
}
