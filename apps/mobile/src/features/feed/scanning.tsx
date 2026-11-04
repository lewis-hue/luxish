import { Image } from 'expo-image';
import { MotiView } from 'moti';
import { useEffect, useState } from 'react';
import { Modal, View, useWindowDimensions } from 'react-native';
import { Easing } from 'react-native-reanimated';

import { ThemedText } from '@/components/themed-text';
import { useMotiTiming } from '@/components/ui/motion';
import { Colors, FontSize, Radius, Spacing, labelType } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * The wait after somebody presses the shutter.
 *
 * **Nine seconds of nothing was the old answer.** Reading a
 * photograph costs five to nine seconds, and the screen showed a
 * button that said "Reading" while the camera roll closed and the
 * search screen sat there. Somebody who has just framed a shot is
 * looking at their picture, not at a button, so the wait belongs
 * over the picture.
 *
 * **It shows their own photograph, scanned.** A band of light passes
 * down the frame and a bracket sits around it, which is the one
 * motion that reads as *this picture is being looked at* rather than
 * as a page loading. The picture underneath is theirs, so the wait
 * is also a confirmation that the right shot was taken.
 *
 * Three stages, timed from what the reader actually does, and the
 * last has no successor: when the read overruns it sits on "Almost
 * there" rather than claiming a step that has not happened. Same
 * rule as the avatar's own card.
 */
const STAGES: readonly string[] = [
  'Looking at the picture',
  'Naming the pieces',
  'Finding the matches',
];

/** How long each line is shown. The read takes five to nine seconds. */
const PER_STAGE_MS = 3000;

/** The scanning band's travel, as a share of the frame. */
const SWEEP_MS = 1800;

/**
 * **Mounted while the read is running, not toggled with a prop.**
 *
 * A `visible` flag meant resetting the stage counter in an effect
 * when it went false, which is the thing `react-hooks/set-state-in-effect`
 * exists to stop - and it is unnecessary here, because a component
 * that only exists during the wait starts at stage zero by being
 * new. The caller renders it conditionally.
 */
export function Scanning({
  uri,
}: {
  /** Their photograph, so the wait is over the thing being read. */
  uri: string | null;
}) {
  const colors = Colors[useScheme()];
  const timing = useMotiTiming();
  const { width } = useWindowDimensions();
  const [stage, setStage] = useState(0);

  useEffect(() => {
    // Stops on the last line rather than wrapping: going back to
    // "Looking at the picture" says the read restarted.
    if (stage >= STAGES.length - 1) return;
    const id = setTimeout(() => setStage((n) => n + 1), PER_STAGE_MS);
    return () => clearTimeout(id);
  }, [stage]);

  const frame = Math.min(width - Spacing.five * 2, 420);
  const tall = frame * 1.25;

  return (
    <Modal visible transparent animationType="fade" statusBarTranslucent>
      <View
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel={STAGES[stage]}
        accessibilityState={{ busy: true }}
        style={{
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
          gap: Spacing.four,
          // Deep enough that the photograph is the only lit thing.
          backgroundColor: 'rgba(16, 12, 11, 0.92)',
        }}>
        <View
          style={{
            width: frame,
            height: tall,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            overflow: 'hidden',
            backgroundColor: 'rgba(255,255,255,0.06)',
          }}>
          {uri ? (
            <Image
              source={{ uri }}
              contentFit="cover"
              style={{ width: '100%', height: '100%' }}
              accessible={false}
            />
          ) : null}

          {/* **The band, travelling the whole frame and back.**

              `repeatReverse` is left at Moti's default here, unlike
              the avatar's ring: a scanner passing down and back up
              is what a scanner does, and the reversal is the motion
              rather than a bug in it. Linear, because a sweep that
              eases reads as hesitant. */}
          <MotiView
            from={{ translateY: -tall * 0.5 }}
            animate={{ translateY: tall * 0.5 }}
            transition={timing({
              duration: SWEEP_MS,
              loop: true,
              repeat: -1,
              easing: Easing.linear,
            })}
            pointerEvents="none"
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              height: tall * 0.26,
              backgroundColor: colors.accent,
              opacity: 0.28,
            }}
          />

          {/* The bracket. Four corners rather than a full border,
              which reads as a viewfinder instead of a picture frame. */}
          {CORNERS.map((corner) => (
            <View
              key={corner.key}
              pointerEvents="none"
              style={{
                position: 'absolute',
                width: 28,
                height: 28,
                borderColor: ON_THE_SCRIM,
                ...corner.style,
              }}
            />
          ))}
        </View>

        <MotiView
          key={stage}
          from={{ opacity: 0, translateY: 6 }}
          animate={{ opacity: 1, translateY: 0 }}
          transition={timing({ duration: 220 })}>
          <ThemedText
            style={{
              ...labelType(FontSize.subhead, 800),
              color: ON_THE_SCRIM,
              textAlign: 'center',
            }}>
            {STAGES[stage]}
          </ThemedText>
        </MotiView>
      </View>
    </Modal>
  );
}

/**
 * White, fixed, not from the palette.
 *
 * The overlay paints its own near-black ground in both schemes, so a
 * token that flips with the scheme would be white-on-white half the
 * time. A colour is only theme-aware where the ground under it is.
 */
const ON_THE_SCRIM = '#FFFFFF';

const EDGE = 2;
const CORNERS = [
  {
    key: 'tl',
    style: { top: 0, left: 0, borderTopWidth: EDGE, borderLeftWidth: EDGE },
  },
  {
    key: 'tr',
    style: { top: 0, right: 0, borderTopWidth: EDGE, borderRightWidth: EDGE },
  },
  {
    key: 'bl',
    style: { bottom: 0, left: 0, borderBottomWidth: EDGE, borderLeftWidth: EDGE },
  },
  {
    key: 'br',
    style: {
      bottom: 0,
      right: 0,
      borderBottomWidth: EDGE,
      borderRightWidth: EDGE,
    },
  },
] as const;
