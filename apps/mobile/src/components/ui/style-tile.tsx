import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import * as Haptics from 'expo-haptics';
import { Platform, Pressable, View, type StyleProp, type ViewStyle } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';

import { ThemedText } from '@/components/themed-text';
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
import { useReducedMotion, useScheme } from '@/hooks/use-theme';

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

type StyleTileProps = {
  asset: InspirationAsset | null;
  title: string;
  subtitle?: string | null;
  meta?: string | null;
  /** Taller treatment for the lead tile. */
  feature?: boolean;
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
  onPress,
  style,
}: StyleTileProps) {
  const colors = Colors[useScheme()];
  const reducedMotion = useReducedMotion();
  const pressed = useSharedValue(0);
  const credit = asset ? attributionLine(asset.source) : null;

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: reducedMotion ? 1 : 1 - pressed.value * 0.025 }],
  }));

  return (
    <AnimatedPressable
      accessibilityRole="button"
      accessibilityLabel={`${title}${subtitle ? `. ${subtitle}` : ''}`}
      accessibilityHint="Opens this style collection"
      onPressIn={() => {
        pressed.value = withSpring(1, { damping: 20, stiffness: 400 });
        // Selection feedback is the lightest tap iOS offers; anything heavier on a
        // browse grid becomes noise within a few scrolls.
        if (Platform.OS !== 'web') void Haptics.selectionAsync();
      }}
      onPressOut={() => {
        pressed.value = withSpring(0, { damping: 20, stiffness: 400 });
      }}
      onPress={onPress}
      style={[
        {
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
        },
        animatedStyle,
        style,
      ]}>
      {asset ? (
        <Image
          source={asset.localSource ?? { uri: asset.uri }}
          placeholder={asset.blurhash ? { blurhash: asset.blurhash } : undefined}
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
        Bottom-weighted scrim. Three stops rather than two: a linear fade leaves a
        visible hard edge where it meets the image, and the midpoint softens it.
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
          padding: feature ? Spacing.four : Spacing.three,
          gap: Spacing.half,
        }}>
        {meta ? (
          <ThemedText
            type="small"
            style={{
              fontSize: FontSize.meta,
              letterSpacing: Tracking.label,
              textTransform: 'uppercase',
              color: 'rgba(255,255,255,0.72)',
            }}>
            {meta}
          </ThemedText>
        ) : null}

        <ThemedText
          numberOfLines={2}
          style={{
            fontFamily: Display.regular,
            fontSize: feature ? 30 : 20,
            lineHeight: feature ? 34 : 23,
            color: '#FFFFFF',
          }}>
          {title}
        </ThemedText>

        {subtitle ? (
          <ThemedText
            type="small"
            numberOfLines={feature ? 3 : 2}
            style={{ color: 'rgba(255,255,255,0.78)', fontSize: feature ? 14 : 12.5 }}>
            {subtitle}
          </ThemedText>
        ) : null}
      </View>

      {/*
        Licence attribution only. The AI-generated badge was removed from the tile
        at the user's request — it is noise on every single card in a grid where
        every image is generated. The disclosure Play policy asks for now lives
        once on the collection detail screen instead of twelve times on the grid,
        and `asset.isGenerated` still carries the fact so nothing is lost.
      */}
      {credit ? (
        <View
          style={{ position: 'absolute', top: Spacing.two, right: Spacing.two }}>
          <Badge label={credit} />
        </View>
      ) : null}
    </AnimatedPressable>
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
