import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import {
  prefetchFitDetail,
  type FeedFit,
} from '@/api/queries/discover-feed';
import { usePostImage } from '@/api/queries/post-media';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Colors, ImageFade, Radius, Spacing } from '@/constants/theme';
import { UNKNOWN_SHAPE, clampShape } from '@/features/feed/shape';
import { useScheme } from '@/hooks/use-theme';

/**
 * One fit on the board: somebody's photograph, and nothing else.
 *
 * **The tile is the card.** It used to carry a row of counts, the
 * author's name and a menu under every picture - five controls each,
 * on a screen holding a hundred and twenty of them. A board of
 * photographs reads as photographs; the same board with a dashboard
 * under each one reads as a dashboard.
 *
 * Everything those controls did is one tap away on the fit itself,
 * which is where somebody who cares about this photograph already is.
 */

/**
 * How tall a tile may get, as a ratio of its width.
 *
 * A board reads by its columns, and one portrait photograph at 9:21
 * pushes everything beside it a screen down. Clamped rather than
 * cropped to a single ratio, which is what made every tile the same
 * height and the board a grid of stamps.
 *
 * The floor is 0.45 because that is the tallest thing anybody here
 * has actually posted: every published cover in the corpus sits
 * inside this range, so the clamp exists for the photograph nobody
 * has uploaded yet rather than cropping the ones they have.
 */
// The bounds live in `shape.ts` now, shared with the grid's column
// maths and with the hero on a fit's own page, because a tile that
// clamps differently from the page it opens is a card that changes
// shape under the tap that opened it.
const RATIO = { until: UNKNOWN_SHAPE } as const;

/**
 * Shapes measured on this device, by asset id.
 *
 * Only ever written for an asset the server could not describe - one
 * uploaded before dimensions were recorded. Remembered for the
 * session, so such a picture seen once lays out correctly the moment
 * it is mounted again. A plain Map rather than state: nothing
 * re-renders when it is written, and the id addresses one immutable
 * file.
 */
const measured = new Map<string, number>();

/**
 * How different a measured shape must be before it is worth a
 * re-layout.
 *
 * Re-measuring a tile moves every tile below it. A thousandth of a
 * ratio is invisible on a 180-point column - well under a tenth of a
 * point of height - so changing the layout for it is all cost and no
 * benefit.
 */
const WORTH_RELAYOUT = 0.005;

export function FitCard({
  fit,
  width,
  onOpen,
  onMore,
}: {
  fit: FeedFit;
  width?: number;
  onOpen?: () => void;
  /**
   * Everything this fit can do, under the tile on the right.
   *
   * Passed only by Discover. A shelf of your own saves is a shelf of
   * pictures you already chose, and a menu glyph on each one is a
   * control for a decision nobody is taking there.
   */
  onMore?: () => void;
}) {
  const colors = Colors[useScheme()];
  const queries = useQueryClient();

  // The photograph's own shape, once it is known. A board of one ratio
  // is a contact sheet; these are somebody's photographs and they are
  // not all the same shape.
  const asset = fit.mediaAssetIds[0] ?? '';
  // What this device measured, for the few covers the server cannot
  // describe. **Carried with the asset it was measured from**, which
  // is the whole point: this list recycles its cells, so a bare
  // number here would be the *previous* fit's shape the moment a cell
  // was reused.
  const [guess, setGuess] = useState<{ asset: string; ratio: number } | null>(
    null,
  );

  // Derived every render rather than latched in state. `useState`'s
  // initialiser runs once per component instance, and a recycled cell
  // is the same instance showing a different fit - so a latched ratio
  // kept the shape of whatever the cell held before, and the column
  // re-flowed around tiles claiming the wrong height. That is the
  // upward lurch people see scrolling a board.
  const ratio =
    fit.coverRatio ??
    (guess?.asset === asset ? guess.ratio : undefined) ??
    measured.get(asset) ??
    RATIO.until;

  // Whether anything is still to be learned from the photograph. When
  // the server sent a shape, the answer is no: it came from the same
  // stored dimensions the file decodes to, and taking the decoded
  // quotient instead would only trade a rounded number for an
  // unrounded one - at the price of re-laying out the column.
  const knowsItsShape = fit.coverRatio !== null;

  const uri = usePostImage(asset).data ?? null;

  const shape = {
    width: '100%',
    aspectRatio: clampShape(ratio),
  } as const;

  return (
    <View style={{ width }}>
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel={`${fit.authorName}. ${fit.caption ?? 'A fit.'}`}
        animateEntrance={false}
        onPress={() => {
          void tapFeedback();
          // Start the fetch on the tap, not on the next screen's
          // first render. A push, a mount and a render all happen
          // before that screen's own query fires, and those
          // milliseconds are the difference between the caption
          // being there when the picture lands and arriving a beat
          // behind it.
          prefetchFitDetail(queries, fit.id);
          onOpen?.();
        }}
        style={{
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
        }}>
        {uri ? (
          <Image
            source={{ uri }}
            // Which fit this view is currently showing. Without it a
            // recycled tile keeps the previous photograph on screen
            // until the new one loads, which is the flash people see
            // scrolling a board.
            recyclingKey={fit.id}
            contentFit="cover"
            transition={ImageFade}
            onLoad={({ source }) => {
              if (knowsItsShape) return;
              if (!source?.width || !source?.height) return;
              const shape = source.width / source.height;
              measured.set(asset, shape);
              if (Math.abs(shape - ratio) > WORTH_RELAYOUT) {
                setGuess({ asset, ratio: shape });
              }
            }}
            style={shape}
          />
        ) : (
          // The frame, at the shape the server said, while the
          // photograph downloads. Sized rather than absent, so the
          // column does not re-flow when it arrives.
          <View style={shape} />
        )}
      </MotionPressable>

      {/* The tile is the card.

          It used to carry a row of counts, the author's name and a
          menu under every photograph: five controls per tile, on a
          screen holding a hundred and twenty of them. Reacting,
          keeping and reading the thread are all one tap away on the
          fit itself, which is where somebody who cares about this
          photograph already is. */}
      {/* Under the tile and hard right, as plain dots on the page.

          Not over the photograph: a chip sitting on the corner of
          somebody's picture covers the thing they posted, and reads
          as chrome the board does not otherwise have. Here it is grey
          type on the background, which is what it is - a way in to a
          menu, not a control competing with the image.

          The band is kept to `Spacing.three` so the distance between
          two pictures down a column stays close to the distance
          across one. It used to be `Spacing.five`, which is where the
          extra white came from. `hitSlop` carries a 16pt row past the
          44pt target without the row itself taking that height. */}
      {onMore ? (
        <View style={{ alignItems: 'flex-end' }}>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={`More for ${fit.authorName}'s fit`}
            animateEntrance={false}
            scale={0.9}
            hitSlop={Spacing.three}
            onPress={() => {
              void tapFeedback();
              onMore();
            }}
            style={{
              height: Spacing.three,
              paddingHorizontal: Spacing.two,
              justifyContent: 'center',
            }}>
            <SymbolView
              name={{ ios: 'ellipsis', android: 'more_horiz', web: 'more_horiz' }}
              size={16}
              tintColor={colors.textSecondary}
            />
          </MotionPressable>
        </View>
      ) : null}
    </View>
  );
}
