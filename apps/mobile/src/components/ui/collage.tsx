import { Image } from 'expo-image';
import { MotiView } from 'moti';
import { useState } from 'react';
import { View, type LayoutChangeEvent } from 'react-native';

import { useMotiTiming } from '@/components/ui/motion';
import { AspectRatio, Radius } from '@/constants/theme';
import { coverFor } from '@/features/discover/imagery';

/**
 * One print in a pile, placed as percentages of the stage.
 *
 * Percentages rather than points so a composition holds at any width: the
 * same cards have to work on a small phone and a tablet, and a layout in
 * points would pull apart on one of them.
 */
export interface CollageFrame {
  /** A cover id. An unknown one renders nothing rather than throwing. */
  id: string;
  alt: string;
  x: number;
  y: number;
  w: number;
  rotate: number;
  delay: number;
  /**
   * How near the front of the pile this print lies, 0 to 1.
   *
   * Optional, and a sheet that omits it gets the flat look every sheet had
   * before: one shadow, no scaling, paint order only. Setting it turns the
   * sheet three-dimensional — see `DEPTH` below for what it drives.
   */
  depth?: number;
}

/**
 * How far toward the middle the cards start, as a fraction of the distance.
 *
 * Not 1. Gathered completely they start as a perfect stack and the spread is
 * a magic trick; at four fifths they start as a loose pile somebody has just
 * set down, and the movement reads as a hand spreading prints rather than a
 * deck exploding.
 */
const GATHER = 0.8;

/**
 * What `depth` is worth, from the back of the pile to the front.
 *
 * Four cues, because one is not convincing. A print nearer the eye is
 * slightly larger, sits in front, carries a longer and darker shadow, and is
 * a shade more present than the ones behind it — that last one is
 * atmospheric perspective, and at seven percent it is felt rather than seen.
 *
 * The numbers are small on purpose. The pile has to read as prints on a
 * table, not as a parallax scene: anything stronger and the back row starts
 * looking like a different, worse photograph.
 */
const DEPTH = {
  scale: [0.95, 1] as const,
  opacity: [0.93, 1] as const,
  shadowY: [3, 8] as const,
  shadowBlur: [9, 23] as const,
  shadowAlpha: [0.1, 0.24] as const,
};

/** The flat sheet's single shadow, for the sheets that declare no depth. */
const FLAT_SHADOW = '0 6px 18px rgba(31,27,26,0.16)';

const mix = ([from, to]: readonly [number, number], t: number) => from + (to - from) * t;

/**
 * A pile of prints, spread out.
 *
 * A row of equal rectangles is a component library; a pile at angles is a
 * moodboard, and a moodboard is what this product is. Two cards at the same
 * angle read as a mistake rather than an arrangement, so every rotation in a
 * sheet differs.
 *
 * **They are dealt, not dropped.** The cards start gathered near the middle
 * of the stage, square-on and slightly small, and travel out to their places
 * picking up their angles as they go — the way somebody spreads photographs
 * across a table. The previous version dropped each card straight down from
 * above its final position, which is the entrance every card component has;
 * this one is a gesture, and it is the same gesture the product is about.
 *
 * It is one orchestrated moment and it plays once. Nothing here loops: a
 * repeating animation beside text is what WCAG 2.2.2 asks for a pause
 * control for, and both motion hooks collapse the whole thing to zero under
 * Reduce Motion, so the composition simply *is* rather than assembling.
 *
 * **Measured before it animates.** The travel is in points, so the stage has
 * to have been laid out before the start positions mean anything. Moti reads
 * `from` once at mount, so the cards wait for the first layout pass rather
 * than mounting at the wrong offset and never recovering.
 */
export function Collage({
  frames,
  /** Stage height as a ratio of its width. Square suits a full-screen sheet;
   *  a shallower stage suits a sheet sitting above a heading. */
  aspectRatio = 1,
  /**
   * How the prints arrive.
   *
   * `spread` eases them out flat, and is right for the three-card sheets
   * that decorate an empty screen — they are a hint at what the screen is
   * for, and a hint should not perform.
   *
   * `deal` lands them one after another, back row first, so the pile
   * visibly builds toward the eye. It costs a second of attention, which
   * only the screen that introduces the product has to spend.
   *
   * An earlier deal turned each card over in 3D on a spring. Twelve views
   * animating `rotateY` under `perspective`, each carrying a shadow and a
   * zIndex, made Android rebuild rendering layers every frame: the whole
   * screen flickered, siblings included. The turn was decoration; the
   * stagger is the gesture, and it survives on the same plain transforms
   * the rest of the app animates.
   */
  entrance = 'spread',
}: {
  frames: readonly CollageFrame[];
  aspectRatio?: number;
  entrance?: 'spread' | 'deal';
}) {
  const timing = useMotiTiming();
  const [width, setWidth] = useState(0);
  const height = width / aspectRatio;
  const dealt = entrance === 'deal';

  const onLayout = (event: LayoutChangeEvent) => {
    const next = event.nativeEvent.layout.width;
    // Guarded: `setState` on every layout pass would restart the deal each
    // time the stage is re-measured, and a rotation re-measures it.
    setWidth((current) => (current === next ? current : next));
  };

  return (
    <View style={{ width: '100%', aspectRatio }} onLayout={onLayout}>
      {width > 0 &&
        frames.map((frame) => {
          const cover = coverFor(frame.id, frame.alt);
          if (!cover) return null;

          // Where this card sits, in points, so the gather can be expressed
          // as a translation rather than as a second set of positions.
          const cardWidth = (frame.w / 100) * width;
          const cardHeight = cardWidth / AspectRatio.editorial;
          const centreX = (frame.x / 100) * width + cardWidth / 2;
          const centreY = (frame.y / 100) * height + cardHeight / 2;

          // Null rather than 0 for a sheet that declares no depth: 0 is the
          // *back* of the pile, which is a real and different answer.
          const depth = frame.depth ?? null;

          return (
            <MotiView
              key={frame.id}
              from={{
                opacity: 0,
                // Toward the middle of the stage, square-on and small: the
                // loose pile the spread starts from.
                translateX: (width / 2 - centreX) * GATHER,
                translateY: (height / 2 - centreY) * GATHER,
                scale: 0.82,
                rotate: '0deg',
              }}
              animate={{
                opacity: depth === null ? 1 : mix(DEPTH.opacity, depth),
                translateX: 0,
                translateY: 0,
                scale: depth === null ? 1 : mix(DEPTH.scale, depth),
                rotate: `${frame.rotate}deg`,
              }}
              // Timing in both modes. A spring was tried for the deal and
              // its overshoot put opacity past 1 on twelve cards at once,
              // which reads as shimmer; an eased landing is what a print
              // actually does.
              transition={timing({ duration: dealt ? 680 : 900, delay: frame.delay })}
              style={{
                position: 'absolute',
                left: `${frame.x}%`,
                top: `${frame.y}%`,
                width: `${frame.w}%`,
                aspectRatio: AspectRatio.editorial,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                overflow: 'hidden',
                // A lift under each card, so overlapping prints read as
                // stacked rather than as one flat collaged image. With depth
                // declared the lift grows toward the front of the pile,
                // which is most of what sells the arrangement as physical.
                boxShadow:
                  depth === null
                    ? FLAT_SHADOW
                    : `0 ${mix(DEPTH.shadowY, depth).toFixed(1)}px ` +
                      `${mix(DEPTH.shadowBlur, depth).toFixed(1)}px ` +
                      `rgba(31,27,26,${mix(DEPTH.shadowAlpha, depth).toFixed(3)})`,
                // Paint order alone would do it while a sheet is authored
                // back-to-front, and would silently invert the pile the
                // first time somebody reordered the array for readability.
                ...(depth === null ? null : { zIndex: Math.round(depth * 100) }),
              }}>
              <Image
                // A card is about 120 points wide; the master is 1120.
                source={cover.thumbSource ?? cover.localSource}
                placeholder={cover.blurhash ? { blurhash: cover.blurhash } : undefined}
                placeholderContentFit="cover"
                contentFit="cover"
                transition={0}
                accessible
                accessibilityLabel={frame.alt}
                style={{ width: '100%', height: '100%' }}
              />
            </MotiView>
          );
        })}
    </View>
  );
}
