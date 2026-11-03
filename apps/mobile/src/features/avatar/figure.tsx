import { Image } from 'expo-image';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Colors, ImageFade, Radius, Spacing } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * An outfit on a figure, drawn on the phone.
 *
 * **No model call, ever.** A photoreal try-on is a billed request of
 * fifteen to twenty-seven seconds, and the common case - "does this
 * top go with those trousers" - does not need one. Every garment here
 * already has a background-removed cut-out, made once when the piece
 * was added, so showing it worn is layering pictures the device
 * already holds. The cost of the hundredth look is the cost of the
 * first.
 *
 * **Stylized on purpose.** The figure is flat and neutral rather than
 * a photograph of a person, because a cut-out laid over a photoreal
 * body invites the eye to check the drape and the shadow and find
 * them wrong. Against a plain figure it reads as what it is: these
 * clothes, in this order, roughly this shape.
 *
 * **Two figures, not one per person.** A render per account is a
 * generation per account; one menswear and one womenswear figure,
 * chosen from the presentation somebody already told us, is two
 * pictures for everybody. Nothing here reads appearance off a
 * photograph or a garment.
 */

/** The figures. Replaced by the generated artwork; same canvas. */
const FIGURES = {
  menswear: require('../../../assets/images/figures/menswear.png'),
  womenswear: require('../../../assets/images/figures/womenswear.png'),
} as const;

export type Presentation = keyof typeof FIGURES | 'unisex' | 'unspecified';

/**
 * Which figure to stand the clothes on.
 *
 * `unisex` and `unspecified` both land on the menswear figure, which
 * is the straighter of the two: a garment laid over it is less
 * distorted than one laid over a shape it was not cut for. This is a
 * drawing decision, not a statement about anybody.
 */
export function figureKeyFor(
  presentation: Presentation,
): keyof typeof FIGURES {
  return presentation === 'womenswear' ? 'womenswear' : 'menswear';
}

export function figureFor(presentation: Presentation) {
  return FIGURES[figureKeyFor(presentation)];
}

/**
 * Where each kind of garment sits, as a share of the frame.
 *
 * Measured against the figures in `assets/images/figures`, so the
 * artwork and these numbers travel together: new figures at the same
 * canvas and proportions need no change here.
 *
 * Ordered back to front. Outerwear is last because a coat goes over
 * everything, and accessories are above it for the same reason a bag
 * hangs outside a coat.
 */
const SLOT_FRAMES = {
  bottoms: { top: 0.5, left: 0.26, width: 0.48, height: 0.42 },
  tops: { top: 0.25, left: 0.22, width: 0.56, height: 0.34 },
  shoes: { top: 0.88, left: 0.3, width: 0.4, height: 0.1 },
  outerwear: { top: 0.24, left: 0.16, width: 0.68, height: 0.44 },
  accessories: { top: 0.44, left: 0.6, width: 0.26, height: 0.2 },
} as const;

export type FigureSlot = keyof typeof SLOT_FRAMES;

/** Back to front, which is also the order a person dresses in. */
export const LAYER_ORDER: readonly FigureSlot[] = [
  'bottoms',
  'tops',
  'shoes',
  'outerwear',
  'accessories',
];

export interface WornPiece {
  id: string;
  slot: FigureSlot;
  /** The cut-out. A piece with no picture is not drawn. */
  uri: string | null;
}

/**
 * Sort the pieces into the order they are drawn in.
 *
 * Exported because it is the rule worth testing: a coat behind a
 * shirt is not a look, it is a bug, and the order must not depend on
 * whatever order the stylist happened to answer in.
 */
export function inLayerOrder(
  pieces: readonly WornPiece[],
): readonly WornPiece[] {
  return [...pieces]
    .filter((piece) => piece.uri !== null)
    .sort(
      (left, right) =>
        LAYER_ORDER.indexOf(left.slot) - LAYER_ORDER.indexOf(right.slot),
    );
}

export function OutfitFigure({
  pieces,
  presentation = 'unspecified',
  label,
}: {
  pieces: readonly WornPiece[];
  presentation?: Presentation;
  /** Read out in place of the pictures, which say nothing on their own. */
  label?: string;
}) {
  const colors = Colors[useScheme()];
  const worn = inLayerOrder(pieces);

  return (
    <View
      accessible
      accessibilityRole="image"
      accessibilityLabel={label ?? 'The outfit, on a figure'}
      style={{
        width: '100%',
        aspectRatio: 3 / 4,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
      }}>
      <Image
        source={figureFor(presentation)}
        contentFit="contain"
        transition={ImageFade}
        style={{ width: '100%', height: '100%' }}
      />

      {worn.map((piece) => {
        const frame = SLOT_FRAMES[piece.slot];
        return (
          <Image
            key={piece.id}
            source={{ uri: piece.uri as string }}
            // `contain`, so a garment keeps its own shape inside the
            // space it is given rather than being stretched to fill
            // it. A stretched jacket is the tell that gives this
            // whole approach away.
            contentFit="contain"
            transition={ImageFade}
            style={{
              position: 'absolute',
              top: `${frame.top * 100}%`,
              left: `${frame.left * 100}%`,
              width: `${frame.width * 100}%`,
              height: `${frame.height * 100}%`,
            }}
          />
        );
      })}

      {worn.length === 0 ? (
        <View
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            alignItems: 'center',
            paddingVertical: Spacing.two,
          }}>
          <ThemedText type="small" themeColor="textSecondary">
            Nothing to put on yet
          </ThemedText>
        </View>
      ) : null}
    </View>
  );
}
