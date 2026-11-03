import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { View, type StyleProp, type ViewStyle } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Colors, FontSize, Radius, Spacing, TapTarget } from '@/constants/theme';
import type { InspirationAsset } from '@/features/discover/types';
import { useScheme } from '@/hooks/use-theme';

export type PinTileProps = {
  asset: InspirationAsset | null;
  /** The line under the picture. Omitted entirely when there is nothing true to say. */
  title?: string | null;
  /** Describes the tile to a screen reader, which cannot see the photograph. */
  label: string;
  /** Picture height as a multiple of its width; the masonry decides it. */
  ratio?: number;
  /** Grid position, for the entrance stagger. */
  index?: number;
  onPress?: () => void;
  /** Opens the actions for this pin. Omit and no `•••` is drawn. */
  onMore?: () => void;
  style?: StyleProp<ViewStyle>;
};

/**
 * One pin in a board.
 *
 * **The caption sits under the picture, not on it.** A label over a
 * photograph needs a scrim to stay legible, and a scrim darkens the bottom
 * third of every garment on the screen. Underneath, the picture is whole and
 * the type is black on paper — which is also how every board-style app worth
 * copying does it.
 *
 * **The picture carries no chrome at all.** The only control is the `•••`
 * beside the caption. Buttons floating over the image are the thing that
 * makes a feed feel like a dashboard; here the tile is the photograph, and
 * everything you can do with it lives on the line below.
 *
 * **Nothing is cropped to a common height.** Each tile keeps the proportion
 * it was given, which is what makes the two columns stagger, and a staggered
 * surface is scanned rather than read row by row.
 */
export function PinTile({
  asset,
  title,
  label,
  ratio = 4 / 3,
  index,
  onPress,
  onMore,
  style,
}: PinTileProps) {
  const colors = Colors[useScheme()];

  return (
    <View style={style}>
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel={label}
        index={index}
        onPress={onPress}
        style={{
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
        }}>
        {asset ? (
          <Image
            source={asset.thumbSource ?? asset.localSource}
            placeholder={asset.blurhash ? { blurhash: asset.blurhash } : undefined}
            contentFit="cover"
            transition={0}
            style={{ width: '100%', aspectRatio: 1 / ratio }}
          />
        ) : (
          <View style={{ width: '100%', aspectRatio: 1 / ratio }} />
        )}
      </MotionPressable>

      {title || onMore ? (
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            // The caption line is the tile's bottom margin as well: a
            // separate gap underneath would double the space between rows.
            paddingTop: Spacing.one,
            gap: Spacing.one,
          }}>
          {title ? (
            <ThemedText
              type="small"
              numberOfLines={1}
              style={{ flex: 1, fontSize: FontSize.footnote }}>
              {title}
            </ThemedText>
          ) : (
            <View style={{ flex: 1 }} />
          )}
          {onMore ? (
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel={`More for ${title ?? label}`}
              animateEntrance={false}
              scale={0.9}
              hitSlop={8}
              onPress={() => {
                void tapFeedback();
                onMore();
              }}
              // Square and tap-target tall, so the caption row keeps the
              // same height whether or not there is a caption to show.
              style={{
                width: TapTarget - Spacing.two,
                height: TapTarget - Spacing.two,
                alignItems: 'flex-end',
                justifyContent: 'center',
              }}>
              <SymbolView
                name={{ ios: 'ellipsis', android: 'more_horiz', web: 'more_horiz' }}
                size={16}
                tintColor={colors.textSecondary}
              />
            </MotionPressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
