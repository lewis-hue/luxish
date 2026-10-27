import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { View, type StyleProp, type ViewStyle } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable } from '@/components/ui/motion';
import {
  AspectRatio,
  Colors,
  Display,
  FontSize,
  Motion,
  Radius,
  Spacing,
  Tracking,
} from '@/constants/theme';
import { attributionLine, type InspirationAsset } from '@/features/discover/types';
import { useScheme } from '@/hooks/use-theme';

type StyleTileProps = {
  asset: InspirationAsset | null;
  title: string;
  subtitle?: string | null;
  meta?: string | null;
  /** Taller treatment for the lead tile. */
  feature?: boolean;
  /** Grid position, for the entrance stagger. */
  index?: number;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
};

/**
 * Image-led tile for the Discover grid.
 *
 * The label sits *on* the photograph behind a gradient scrim rather than in a band
 * beneath it — a band turns a fashion grid into a file listing. The scrim is what
 * makes that safe: white text on an unknown image is a contrast gamble, and the
 * gradient guarantees a dark ground under the text regardless of what the photograph
 * does there.
 *
 * Press feedback is a spring scale rather than an opacity fade, because fading a
 * photograph reads as "loading" instead of "pressed". It collapses to nothing when
 * the user has asked for reduced motion.
 */
export function StyleTile({
  asset,
  title,
  subtitle,
  meta,
  feature,
  index,
  onPress,
  style,
}: StyleTileProps) {
  const colors = Colors[useScheme()];
  const credit = asset ? attributionLine(asset.source) : null;

  const tile = (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={`${title}${subtitle ? `. ${subtitle}` : ''}`}
      accessibilityHint="Opens this style collection"
      index={index}
      onPress={onPress}
      style={[
        {
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
        },
        // In grid mode the caller's style belongs to the wrapper that holds
        // the image *and* its caption, not to the image alone, or `flex: 1`
        // would size the photograph and leave the text unaligned.
        feature ? style : undefined,
      ]}>
      {asset ? (
        <Image
          source={asset.localSource ?? { uri: asset.uri }}
          placeholder={asset.blurhash ? { blurhash: asset.blurhash } : undefined}
          // `placeholderContentFit` defaults to 'scale-down' while
          // `contentFit` defaults to 'cover'; expo-image's own docs warn the
          // mismatch causes flickering, so they are matched explicitly.
          placeholderContentFit="cover"
          // Without a recycling key a recycled cell shows the previous
          // image until the new one decodes, which on a fast scroll looks
          // like the wrong garment.
          recyclingKey={asset.uri}
          cachePolicy="memory-disk"
          contentFit="cover"
          transition={Motion.base}
          accessible={false}
          style={{
            width: '100%',
            aspectRatio: feature ? 4 / 5 : AspectRatio.editorial,
          }}
        />
      ) : (
        <TypographicCover title={title} feature={feature} />
      )}

      {/*
        The label sits ON the photograph only for the feature tile, and BELOW
        it on paper for grid tiles.

        That split is not a preference. Every premium reference measured puts
        product text below the image: NET-A-PORTER, SSENSE, Indyx and MR
        PORTER all do, and none overlays. Material 3 is blunter still: "It
        isn't recommended to place text or icons on images. If it's necessary,
        ensure the background image provides sufficient contrast... Add a
        translucent scrim or bounding shape."

        White text over an unknown photograph is a contrast gamble, and a
        scrim is what makes it safe. On a grid of twelve tiles that gamble is
        taken twelve times and darkens twelve photographs to pay for it, in an
        app where the photographs are the content. On a single full-bleed hero
        the scrim is affordable: it is one image, it is large, and the text is
        the reason the hero exists.
      */}
      {feature ? (
        <>
          {/*
            Three stops rather than two: a linear fade leaves a visible hard
            edge where it meets the image, and the midpoint softens it.
          */}
          <LinearGradient
            colors={['transparent', 'rgba(16,12,11,0.35)', 'rgba(16,12,11,0.88)']}
            locations={[0.35, 0.62, 1]}
            pointerEvents="none"
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: '68%',
            }}
          />

          <View
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              padding: Spacing.four,
              gap: Spacing.half,
            }}>
            {meta ? <TileMeta label={meta} onImage /> : null}
            <ThemedText
              numberOfLines={2}
              style={{
                fontFamily: Display.regular,
                fontSize: 30,
                lineHeight: 34,
                color: '#FFFFFF',
              }}>
              {title}
            </ThemedText>
            {subtitle ? (
              <ThemedText
                type="small"
                numberOfLines={3}
                style={{ color: 'rgba(255,255,255,0.78)', fontSize: FontSize.footnote }}>
                {subtitle}
              </ThemedText>
            ) : null}
          </View>
        </>
      ) : null}

      {/*
        Licence attribution only. The AI-generated badge was removed from the
        tile at the user's request: it is noise on every single card in a grid
        where every image is generated. The disclosure Play policy asks for
        lives once on the collection detail screen instead of twelve times on
        the grid, and `asset.isGenerated` still carries the fact.
      */}
      {credit ? (
        <View style={{ position: 'absolute', top: Spacing.two, right: Spacing.two }}>
          <Badge label={credit} />
        </View>
      ) : null}
    </MotionPressable>
  );

  if (feature) return tile;

  return (
    <View style={[{ gap: Spacing.two }, style]}>
      {tile}
      <View style={{ gap: 2, paddingHorizontal: Spacing.half }}>
        {meta ? <TileMeta label={meta} /> : null}
        <ThemedText
          numberOfLines={2}
          style={{
            fontFamily: Display.regular,
            fontSize: FontSize.title3,
            lineHeight: 23,
            color: colors.text,
          }}>
          {title}
        </ThemedText>
        {subtitle ? (
          <ThemedText
            type="small"
            numberOfLines={2}
            themeColor="textSecondary"
            style={{ fontSize: FontSize.caption }}>
            {subtitle}
          </ThemedText>
        ) : null}
      </View>
    </View>
  );
}

/** The small tracked caps label above a tile title. */
function TileMeta({ label, onImage }: { label: string; onImage?: boolean }) {
  const colors = Colors[useScheme()];
  return (
    <ThemedText
      type="small"
      style={{
        fontSize: FontSize.meta,
        letterSpacing: Tracking.label,
        textTransform: 'uppercase',
        color: onImage ? 'rgba(255,255,255,0.72)' : colors.textSecondary,
      }}>
      {label}
    </ThemedText>
  );
}

/** Editorial fallback while a cover is missing. */
function TypographicCover({ title, feature }: { title: string; feature?: boolean }) {
  const colors = Colors[useScheme()];
  return (
    <View
      accessible={false}
      style={{
        width: '100%',
        aspectRatio: feature ? 4 / 5 : AspectRatio.editorial,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.backgroundSelected,
      }}>
      <ThemedText
        style={{
          fontFamily: Display.regular,
          fontSize: feature ? 96 : 72,
          lineHeight: feature ? 104 : 80,
          color: colors.accent,
        }}>
        {title.trim().charAt(0).toUpperCase()}
      </ThemedText>
    </View>
  );
}

function Badge({ label }: { label: string }) {
  return (
    <View
      style={{
        paddingHorizontal: Spacing.two,
        paddingVertical: 3,
        borderRadius: Radius.full,
        // Dark pill rather than a tinted one: it has to sit legibly on an
        // unpredictable photograph, and the accent does not always.
        backgroundColor: 'rgba(16,12,11,0.55)',
      }}>
      <ThemedText
        type="small"
        numberOfLines={1}
        style={{
          fontSize: FontSize.meta,
          letterSpacing: Tracking.label,
          textTransform: 'uppercase',
          color: 'rgba(255,255,255,0.9)',
        }}>
        {label}
      </ThemedText>
    </View>
  );
}
