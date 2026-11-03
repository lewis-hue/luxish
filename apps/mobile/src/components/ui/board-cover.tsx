import { Image } from 'expo-image';
import { StyleSheet, View } from 'react-native';

import { usePostImage } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { AspectRatio, Colors, FontSize, Radius, Spacing } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/** How many pins a cover shows. Four is a square; more is a mosaic nobody reads. */
const FACES = 4;

/** One pinned fit, as a board reports it. */
export interface BoardFace {
  postId: string;
  /** Null when the fit has no photograph this reader may see. */
  coverAssetId: string | null;
}

/**
 * A board, shown as the first few things on it.
 *
 * **The board is its own cover**, rather than carrying a chosen image. A
 * collection's cover *is* what is in it, and asking somebody to pick one
 * makes a second decision out of an act that should be one. It also keeps a
 * board honest: it cannot look fuller than it is.
 *
 * One pin fills the frame, two split it, three or more make a grid with the
 * first pin given the larger half. That asymmetry is deliberate — four equal
 * squares is a component library's idea of a collage.
 *
 * **It draws the fits on the board.** It used to draw catalogue artwork
 * from the look ids a board carried, which is why a board full of
 * pinned photographs came out reading "Empty": the pins were there,
 * the ids it was looking for were not.
 */
export function BoardCover({ faces }: { faces: readonly BoardFace[] }) {
  const colors = Colors[useScheme()];
  const shown = faces.slice(0, FACES);

  if (shown.length === 0) {
    return (
      <View
        style={{
          aspectRatio: 1,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.meta }}>
          Empty
        </ThemedText>
      </View>
    );
  }

  return (
    <View
      style={{
        aspectRatio: 1,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
        flexDirection: 'row',
        // A hairline between the faces, so two photographs that happen to
        // share a tone still read as two. `hairlineWidth` rather than a
        // number: this is a rule, not spacing, and the thinnest visible line
        // is a different width on different screens.
        gap: StyleSheet.hairlineWidth,
      }}>
      <Face face={shown[0]} flex={shown.length === 1 ? 1 : 1.2} />
      {shown.length > 1 ? (
        <View style={{ flex: 1, gap: StyleSheet.hairlineWidth }}>
          {shown.slice(1).map((face) => (
            <Face key={face.postId} face={face} flex={1} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Face({ face, flex }: { face: BoardFace; flex: number }) {
  const colors = Colors[useScheme()];
  const uri = usePostImage(face.coverAssetId).data ?? null;

  if (!uri) {
    // Not yet downloaded, or a fit taken down since it was pinned. A
    // tinted gap rather than a hole, so the board keeps its shape and
    // nobody is told their board is broken.
    return <View style={{ flex, backgroundColor: colors.backgroundSelected }} />;
  }

  return (
    <Image
      source={{ uri }}
      // Covers are drawn in a recycling grid of boards, so each face
      // has to say which fit it is showing or it keeps the previous
      // one until the next decodes.
      recyclingKey={face.postId}
      contentFit="cover"
      cachePolicy="memory-disk"
      accessible={false}
      style={{ flex }}
    />
  );
}

/** The ratio a board tile sits at in a grid of boards. */
export const BOARD_RATIO = AspectRatio.editorial;

/** Shared padding for a board tile's caption. */
export const BOARD_CAPTION_GAP = Spacing.half;
