import { Image } from 'expo-image';

import { Colors } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * Paper grain, laid over the whole screen.
 *
 * A flat digital ground is the one thing a printed fashion page never has.
 * A film grain over it is what the covers already carry — they are generated
 * "shot on medium format film, natural grain" — so without it the paper
 * between the photographs is visibly cleaner than the photographs, and the
 * pictures read as pasted onto a screen rather than printed on a page.
 *
 * **Generated with a seeded RNG, not by the image model.** Grain is
 * pseudo-random noise, which a seeded generator produces exactly and a
 * billed call produces approximately. The tile is black specks at alpha 0 to
 * 16 and nothing else: mixing light and dark specks in one tile makes
 * television static. The single tone is then tinted per theme at render, so
 * it is dark specks on paper and light specks on the dark ground.
 *
 * **Rendered last, over the content.** Grain is a property of the printed
 * page, not of the paper beneath the ink. Underneath, it was occluded by
 * anything opaque drawn on top — including the page-coloured silhouette
 * masks that hide the drawn floor behind a figure's body, which then read as
 * flat cut-outs of each person against grained paper.
 *
 * `pointerEvents="none"` and no accessibility label, because it is texture.
 * Anything announced here would be read out on every screen that uses it.
 */
export function Grain({ opacity = 0.5 }: { opacity?: number }) {
  const colors = Colors[useScheme()];
  return (
    <Image
      source={require('../../../assets/images/texture/grain.webp')}
      // Stretched across the screen rather than tiled: React Native's repeat
      // mode is iOS-only, and one 512px tile scaled over a phone keeps the
      // specks sub-pixel, which is the only size grain may be.
      contentFit="cover"
      // **Tinted, or it only works in one theme.** The tile is black specks
      // on transparency, which is right on warm paper and mathematically
      // invisible on the dark ground — black over near-black is no change at
      // all. Tinting to the text colour makes it light specks in dark mode,
      // which is what grain on a dark print actually looks like.
      tintColor={colors.text as string}
      transition={0}
      accessible={false}
      pointerEvents="none"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        opacity,
        // Over everything. See the note in `welcome.tsx`: underneath, it
        // left every masked figure as a grainless cut-out against grained
        // paper.
        zIndex: 20,
      }}
    />
  );
}
