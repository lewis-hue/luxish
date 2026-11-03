import LottieView from 'lottie-react-native';
import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { Colors, Motion } from '@/constants/theme';
import { useReducedMotion, useScheme } from '@/hooks/use-theme';

/**
 * The mark that confirms something you just did.
 *
 * A stroke that draws itself, which is the one thing worth reaching for
 * Lottie to get: a trim path along a vector is not something Reanimated
 * expresses, and the alternative — fading a finished tick in — says "a tick
 * appeared" rather than "that was recorded".
 *
 * **It is a reward, never a loader.** ADR-019 settled that a looping or
 * shimmering animation beside other content fails WCAG 2.2.2, because the
 * loading-animation exemption only applies when the animation is the only
 * thing on the page. This plays once, on an action somebody took, and then it
 * is gone — the case 2.2.2 does not cover, and the only case this component
 * is for. Do not reach for it to fill a wait.
 *
 * **Mount it to play it.** There is no `play` prop and that is deliberate: a
 * boolean would need an effect to notice it flipping, and an effect that
 * synchronously sets state is both a lint error here and a cascading render.
 * The caller renders it with a key that changes per confirmation
 * (`useConfirmMark` below), so a new mark is a new component and replaying is
 * just mounting again.
 */
export function ConfirmMark({
  size = 28,
  /** Defaults to the accent, which is what the 10 in 60/30/10 is for. */
  color,
  accessibilityLabel,
}: {
  size?: number;
  color?: string;
  accessibilityLabel: string;
}) {
  const colors = Colors[useScheme()];
  const reduced = useReducedMotion();
  const lottie = useRef<LottieView>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    if (!reduced) lottie.current?.play();
    // Cleared rather than left on screen. A confirmation that stays is no
    // longer a confirmation; it is a badge nobody asked for. The state change
    // happens in the timer callback, not in the effect body.
    const clear = setTimeout(() => setGone(true), reduced ? Motion.slow : 900);
    return () => clearTimeout(clear);
  }, [reduced]);

  if (gone) return null;

  return (
    <View
      accessible
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
      pointerEvents="none"
      style={{ width: size, height: size }}>
      <LottieView
        ref={lottie}
        source={require('../../../assets/lottie/saved.json')}
        autoPlay={false}
        loop={false}
        // The file is authored in white so one asset serves both themes and
        // both tints; the colour is applied here from the palette rather than
        // baked into the vector.
        colorFilters={[{ keypath: 'mark', color: color ?? colors.accent }]}
        // Reduce Motion holds the finished frame: the mark is still drawn, it
        // just does not travel. A shortened version of an unwanted animation
        // is still unwanted.
        progress={reduced ? 1 : undefined}
        style={{ width: size, height: size }}
      />
    </View>
  );
}

/**
 * The counter that makes a confirmation replayable.
 *
 * `confirm()` on the action, then render `<ConfirmMark key={token} />` when
 * `token > 0`. Each call is a new key, so the same confirmation twice in a
 * row plays twice rather than sitting there already finished.
 */
export function useConfirmMark(): { token: number; confirm: () => void } {
  const [token, setToken] = useState(0);
  return { token, confirm: () => setToken((previous) => previous + 1) };
}
