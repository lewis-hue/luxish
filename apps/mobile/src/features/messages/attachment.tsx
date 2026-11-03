import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useState } from 'react';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ImageViewer } from '@/components/ui/image-viewer';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/** How wide an attachment is drawn in a bubble. */
const WIDE = 220;

/**
 * Minutes and seconds, from milliseconds.
 *
 * Exported for its test: a voice note that says `1:7` instead of
 * `1:07` is the kind of thing nobody notices until it ships.
 */
export function clockFace(millis: number): string {
  if (!Number.isFinite(millis) || millis <= 0) return '0:00';
  const total = Math.round(millis / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Whatever somebody attached, drawn as the thing it is.
 *
 * **One component because the bubble should not know.** A thread
 * used to assume every attachment was a photograph - it rendered an
 * `Image` and nothing else - so a video would have arrived as a
 * broken picture and a voice note as nothing at all. The server now
 * says which of the three it is; this is what draws each.
 */
export function Attachment({
  uri,
  kind,
  label,
}: {
  uri: string | null;
  /** `image`, `video` or `audio`, as the server classified it. */
  kind: string | null;
  label?: string;
}) {
  if (!uri || !kind) return null;
  if (kind === 'video') return <VideoBubble uri={uri} label={label} />;
  if (kind === 'audio') return <VoiceNote uri={uri} />;
  return <PictureBubble uri={uri} label={label} />;
}

function PictureBubble({ uri, label }: { uri: string; label?: string }) {
  const colors = Colors[useScheme()];
  const [open, setOpen] = useState(false);

  return (
    <>
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel="Open this picture"
        animateEntrance={false}
        animatePress={false}
        onPress={() => {
          void tapFeedback();
          setOpen(true);
        }}
        style={{
          width: WIDE,
          aspectRatio: 3 / 4,
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
        }}>
        <Image
          source={{ uri }}
          contentFit="cover"
          transition={ImageFade}
          accessible={false}
          style={{ width: '100%', height: '100%' }}
        />
      </MotionPressable>
      <ImageViewer
        uri={uri}
        visible={open}
        label={label}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

/**
 * A video, playable where it sits.
 *
 * **Not auto-playing.** A thread scrolled past three videos would
 * otherwise be three soundtracks at once, and somebody reading in
 * company has had their phone make a noise they did not ask for.
 * Native controls, because every video anybody has ever played on
 * this phone has had those and they already know where they are.
 */
function VideoBubble({ uri, label }: { uri: string; label?: string }) {
  const colors = Colors[useScheme()];
  const player = useVideoPlayer(uri, (instance) => {
    instance.loop = false;
  });

  return (
    <View
      accessible
      accessibilityLabel={label ?? 'A video'}
      style={{
        width: WIDE,
        aspectRatio: 3 / 4,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
      }}>
      <VideoView
        player={player}
        nativeControls
        contentFit="cover"
        style={{ width: '100%', height: '100%' }}
      />
    </View>
  );
}

/**
 * A voice note: a play button, and how long it runs.
 *
 * **A bar rather than a player.** A voice note is a sentence
 * somebody spoke; a scrubber, a volume slider and a timeline are a
 * media player's worth of furniture around a few seconds of speech.
 * One control, and the length so nobody has to commit to an unknown
 * amount of listening before they start.
 */
function VoiceNote({ uri }: { uri: string }) {
  const colors = Colors[useScheme()];
  const player = useAudioPlayer(uri);
  const status = useAudioPlayerStatus(player);

  const playing = status?.playing ?? false;
  // While it runs, how far through; before it starts, how long it is.
  const shown = playing
    ? clockFace((status?.currentTime ?? 0) * 1000)
    : clockFace((status?.duration ?? 0) * 1000);

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={playing ? 'Pause this voice note' : 'Play this voice note'}
      accessibilityState={{ busy: playing }}
      animateEntrance={false}
      scale={0.97}
      onPress={() => {
        void tapFeedback();
        if (playing) {
          player.pause();
          return;
        }
        // From the beginning when it has already run through, so a
        // second tap replays rather than doing nothing at the end.
        if ((status?.currentTime ?? 0) >= (status?.duration ?? 0)) {
          void player.seekTo(0);
        }
        player.play();
      }}
      style={{
        width: WIDE,
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget,
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
      }}>
      <SymbolView
        name={
          playing
            ? { ios: 'pause.fill', android: 'pause', web: 'pause' }
            : { ios: 'play.fill', android: 'play_arrow', web: 'play_arrow' }
        }
        size={20}
        tintColor={colors.text}
      />
      <ThemedText style={{ ...labelType(FontSize.subhead, 400), flex: 1 }}>
        Voice note
      </ThemedText>
      <ThemedText
        themeColor="textSecondary"
        style={{
          ...labelType(FontSize.meta, 400),
          // The number changes under the finger while it plays.
          fontVariant: ['tabular-nums'],
        }}>
        {shown}
      </ThemedText>
    </MotionPressable>
  );
}
