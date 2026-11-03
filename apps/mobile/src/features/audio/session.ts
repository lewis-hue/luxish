import { setAudioModeAsync } from 'expo-audio';

/**
 * Putting the audio session into the state recording needs.
 *
 * **Nothing records until this is called, and nothing says so.** The
 * session is configured for playback by default, so on iOS
 * `prepareToRecordAsync`, `record()` and `stream.start()` all
 * resolve, no error is raised anywhere, and the file that comes back
 * is silent or empty. Both of this app's recorders - the voice note
 * in a thread and the hold-to-talk on the stylist - were written
 * without it and neither captured anything.
 *
 * It is a pair, and the second half matters as much as the first:
 * an iOS session left in recording mode routes playback to the
 * earpiece, so every sound the app makes afterwards comes out of the
 * small speaker by somebody's ear instead of the loud one.
 *
 * Both are quiet on failure. A session that cannot be configured is
 * reported by the recording not working, which the caller already
 * handles; a dialog here would be a second one about the same thing.
 */
export async function openForRecording(): Promise<void> {
  try {
    await setAudioModeAsync({
      allowsRecording: true,
      // Somebody who has silenced their phone still means to record
      // when they hold a microphone button down.
      playsInSilentMode: true,
    });
  } catch {
    // The recorder's own failure path reports this.
  }
}

/** Hand the session back, so playback is not stuck on the earpiece. */
export async function backToPlayback(): Promise<void> {
  try {
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
  } catch {
    // Nothing useful to do, and nothing worth interrupting anybody for.
  }
}
