import {
  requestRecordingPermissionsAsync,
  useAudioStream,
} from 'expo-audio';
import { SymbolView } from 'expo-symbols';
import { useRef, useState } from 'react';
import { Alert, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { Colors, FontSize, Radius, Spacing, TapTarget } from '@/constants/theme';
import { backToPlayback, openForRecording } from '@/features/audio/session';
import { useScheme } from '@/hooks/use-theme';
import {
  CHANNELS,
  SAMPLE_RATE,
  TooShort,
  transcribe,
} from '@/features/stylist/voice';

/**
 * Hold to talk to the stylist.
 *
 * **Hold, not tap-to-start-and-tap-to-stop.** A toggle leaves people
 * recording after they have walked away from the phone, and the only
 * way to find out is the bill. Holding bounds the recording to the
 * length of a gesture somebody is actively making.
 *
 * **The transcript lands in the field, not in the request.** What comes
 * back is a guess at what was said, and the person has to be able to
 * read and fix it before it becomes a question — so this appends to the
 * composer rather than submitting.
 *
 * **Nothing is kept.** The audio goes up, text comes back, the buffer is
 * dropped. A voice note dictated to pick an outfit is not something
 * anybody asked to store.
 */
export function MicButton({
  onText,
  compact = false,
}: {
  onText: (text: string) => void;
  /**
   * Icon only, sized to sit on the edge of the composer.
   *
   * The full button carries its own label and a line about what happens
   * to the audio. Inside a text field that is three rows of furniture
   * around a one-line request, so the compact form drops to the icon and
   * the state it is in, and the accessibility label carries the rest.
   */
  compact?: boolean;
}) {
  const colors = Colors[useScheme()];
  const [recording, setRecording] = useState(false);
  const [working, setWorking] = useState(false);
  /** The file being written, so a release knows there is one to finish. */
  const writing = useRef(false);

  // `int16` rather than the default `float32`: a 16-bit WAV is what the
  // vendor's ASR expects, and asking the platform for it avoids a
  // conversion on the way out.
  const { stream } = useAudioStream({
    sampleRate: SAMPLE_RATE,
    channels: CHANNELS,
    encoding: 'int16',
  });

  const start = async () => {
    const { granted } = await requestRecordingPermissionsAsync();
    if (!granted) {
      Alert.alert(
        'Microphone access needed',
        'Grant access in Settings to talk to the stylist. Typing keeps working.',
      );
      return;
    }
    void tapFeedback();
    setRecording(true);
    try {
      // Nothing is captured until the session allows it, and nothing
      // raises when it does not: `stream.start()` resolves and the
      // file comes back empty. See `features/audio/session`.
      await openForRecording();
      await stream.start();
      // Written straight to a WAV by the platform: see `voice.ts` for
      // why that matters more than it sounds.
      await stream.startFileRecordingAsync({ format: 'wav' });
      writing.current = true;
    } catch {
      setRecording(false);
      Alert.alert('Could not start recording', 'Try again, or type it.');
    }
  };

  const stop = async () => {
    if (!recording) return;
    setRecording(false);
    if (!writing.current) {
      stream.stop();
      // The brush-of-the-button path. It opened the session too, so
      // it has to hand it back or playback stays on the earpiece
      // after a gesture that recorded nothing.
      await backToPlayback();
      return;
    }

    setWorking(true);
    try {
      const file = await stream.stopFileRecordingAsync();
      writing.current = false;
      stream.stop();
      // Or every sound afterwards comes out of the earpiece.
      await backToPlayback();
      const text = await transcribe(file.uri, file.duration);
      if (text) {
        void successFeedback();
        onText(text);
      }
    } catch (caught) {
      // A brush of the button is not an error worth a dialog.
      if (!(caught instanceof TooShort)) {
        Alert.alert('Could not hear that', (caught as Error).message);
      }
    } finally {
      writing.current = false;
      setWorking(false);
    }
  };

  const label = working ? 'Turning that into words' : recording ? 'Listening' : 'Hold to talk';

  if (compact) {
    return (
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel="Hold to talk to the stylist"
        accessibilityHint="Records while held, then puts what you said in the field. The audio is not kept."
        accessibilityState={{ busy: working || recording, disabled: working }}
        disabled={working}
        animateEntrance={false}
        scale={0.9}
        onPressIn={() => void start()}
        onPressOut={() => void stop()}
        style={{
          width: TapTarget,
          height: TapTarget,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: Radius.full,
          backgroundColor: recording ? colors.accent : 'transparent',
          opacity: working ? 0.5 : 1,
        }}>
        <SymbolView
          name={{
            ios: recording ? 'waveform' : 'mic',
            android: recording ? 'graphic_eq' : 'mic',
            web: 'mic',
          }}
          size={18}
          tintColor={recording ? colors.accentText : colors.textSecondary}
        />
      </MotionPressable>
    );
  }

  return (
    <View style={{ gap: Spacing.one }}>
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel="Hold to talk to the stylist"
        accessibilityHint="Records while held, then puts what you said in the field"
        accessibilityState={{ busy: working || recording, disabled: working }}
        disabled={working}
        animateEntrance={false}
        scale={0.96}
        onPressIn={() => void start()}
        onPressOut={() => void stop()}
        style={{
          minHeight: TapTarget,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: Spacing.two,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          borderWidth: 1,
          borderColor: recording ? colors.accent : colors.border,
          backgroundColor: recording ? colors.accent : 'transparent',
          opacity: working ? 0.6 : 1,
        }}>
        <SymbolView
          name={{
            ios: recording ? 'waveform' : 'mic',
            android: recording ? 'graphic_eq' : 'mic',
            web: 'mic',
          }}
          size={18}
          tintColor={recording ? colors.accentText : colors.text}
        />
        <ThemedText
          type="small"
          style={{ color: recording ? colors.accentText : colors.text }}>
          {label}
        </ThemedText>
      </MotionPressable>
      <ThemedText
        type="small"
        themeColor="textSecondary"
        style={{ fontSize: FontSize.meta }}>
        What you say is turned into text and not kept.
      </ThemedText>
    </View>
  );
}
