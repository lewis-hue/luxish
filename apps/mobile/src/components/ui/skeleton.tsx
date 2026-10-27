import { useEffect, useState } from 'react';
import { View, type DimensionValue, type ViewStyle } from 'react-native';

import { Colors, Radius, Spacing } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * Loading placeholders that hold the shape of the content.
 *
 * **These do not shimmer, and that is a decision rather than an omission.**
 *
 * WCAG 2.2.2 requires a pause/stop/hide mechanism for motion that starts
 * automatically, lasts over five seconds, and is presented in parallel with
 * other content. There is an exemption for loading animations, but reading the
 * Understanding document, it is conditioned on the animation being *the only
 * content on the page*: "Because the moving content is not presented in
 * parallel with other content, no mechanism to pause, stop or hide it needs to
 * be provided." A shimmering grid sitting under our live, tappable tab bar is
 * by construction not the only content, so the exemption does not apply and
 * the criterion is met rather than escaped. The "essential" get-out does not
 * help either: it requires that interaction cannot occur during the phase, and
 * the tab bar is interactive throughout.
 *
 * A static placeholder conveys "loading" perfectly well, so the motion was
 * never load-bearing. Honouring `prefers-reduced-motion` alone would not fix
 * it, because 2.2.2 wants a mechanism regardless of OS preference.
 *
 * The other half of the decision: most of the time there should be no skeleton
 * at all. Nielsen Norman Group's guidance is that under one second no
 * indicator should be shown, because "the quick flashing page can cause users
 * to feel like they can't keep up". `useDelayedVisible` enforces that.
 */

/** Below this, showing anything is worse than showing nothing. */
export const SKELETON_DELAY_MS = 400;

/**
 * True once `active` has been true continuously for `delay`.
 *
 * Stops a placeholder flashing on a fast load. Returns false immediately when
 * `active` goes false, so content never waits on the delay.
 */
export function useDelayedVisible(active: boolean, delay = SKELETON_DELAY_MS): boolean {
  const [elapsed, setElapsed] = useState(false);

  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => setElapsed(true), delay);
    return () => {
      clearTimeout(timer);
      // Reset in cleanup rather than in the effect body. Setting state
      // synchronously in the body triggers a cascading render, and React's
      // lint rule rightly rejects it; cleanup runs exactly when `active`
      // flips, which is when the reset is wanted.
      setElapsed(false);
    };
  }, [active, delay]);

  // Derived, not stored. `active` going false hides the placeholder on the
  // same render, so content never waits for a state update to land.
  return active && elapsed;
}

/**
 * One placeholder block.
 *
 * Accessible as a single "busy" element rather than as decorative scenery: a
 * screen reader should hear that something is loading, not silence.
 */
export function Skeleton({
  width = '100%',
  height,
  radius = Radius.sm,
  style,
  label,
}: {
  width?: DimensionValue;
  height: number;
  radius?: number;
  style?: ViewStyle;
  label?: string;
}) {
  const colors = Colors[useScheme()];
  return (
    <View
      accessible={label !== undefined}
      accessibilityRole={label !== undefined ? 'progressbar' : undefined}
      accessibilityLabel={label}
      accessibilityState={label !== undefined ? { busy: true } : undefined}
      style={[
        {
          width,
          height,
          borderRadius: radius,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
        },
        style,
      ]}
    />
  );
}

/** A placeholder image cell, holding its real aspect ratio so nothing reflows. */
export function SkeletonImage({
  aspectRatio,
  radius = Radius.md,
  style,
}: {
  aspectRatio: number;
  radius?: number;
  style?: ViewStyle;
}) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={[
        {
          width: '100%',
          aspectRatio,
          borderRadius: radius,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
        },
        style,
      ]}
    />
  );
}

/**
 * Placeholder text lines.
 *
 * The last line is shortened because real text rarely fills its final line,
 * and a block of equal-length bars reads as a table rather than prose.
 */
export function SkeletonText({
  lines = 2,
  lineHeight = 12,
  gap = Spacing.one,
}: {
  lines?: number;
  lineHeight?: number;
  gap?: number;
}) {
  return (
    <View style={{ gap }}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          height={lineHeight}
          width={index === lines - 1 ? '62%' : '100%'}
          radius={lineHeight / 2}
        />
      ))}
    </View>
  );
}

/**
 * A grid of image placeholders matching the real grid's geometry.
 *
 * Announced once for the whole grid. Twelve individually "busy" cells would be
 * read out twelve times, which is worse than saying nothing.
 */
export function SkeletonGrid({
  count = 6,
  columns = 2,
  aspectRatio,
  gutter = Spacing.two,
  withCaption = true,
  label = 'Loading',
}: {
  count?: number;
  columns?: number;
  aspectRatio: number;
  gutter?: number;
  withCaption?: boolean;
  label?: string;
}) {
  const rows = Math.ceil(count / columns);
  return (
    <View
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={label}
      accessibilityState={{ busy: true }}
      style={{ gap: gutter }}>
      {Array.from({ length: rows }, (_, row) => (
        <View key={row} style={{ flexDirection: 'row', gap: gutter }}>
          {Array.from({ length: columns }, (_, column) => {
            const index = row * columns + column;
            if (index >= count) {
              // An empty spacer, so a short final row stays aligned left
              // instead of stretching its cells.
              return <View key={column} style={{ flex: 1 }} />;
            }
            return (
              <View key={column} style={{ flex: 1, gap: Spacing.one }}>
                <SkeletonImage aspectRatio={aspectRatio} />
                {withCaption ? <SkeletonText lines={1} lineHeight={10} /> : null}
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}
