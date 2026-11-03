/**
 * Talking to the stylist instead of typing at it.
 *
 * **WAV, written by the platform.** The transcription endpoint accepts
 * WAV and nothing else (verified against the vendor), and neither of
 * `expo-audio`'s recording presets produces one — `HIGH_QUALITY` is m4a,
 * `LOW_QUALITY` is m4a on iOS and 3gp on Android. `AudioStream`'s
 * `startFileRecordingAsync({ format: 'wav' })` does, on both platforms,
 * with a header the OS keeps valid as it writes. That is the whole
 * reason this uses the stream API rather than the recorder.
 *
 * **Nothing is kept.** The file is written to the cache, read once,
 * uploaded, and deleted. A voice note dictated to pick an outfit is not
 * something anybody asked to store, and the transcript that comes back
 * is editable text in a field rather than a submitted request.
 */

import { File } from 'expo-file-system';

import { api } from '@/api/client';

/** What the endpoint takes, and what the hardware is asked for. */
export const SAMPLE_RATE = 16_000;
export const CHANNELS = 1;

/** The vendor's ceiling. Longer than anybody dictates an outfit request. */
export const MAX_SECONDS = 600;

/**
 * Below this a recording is a mistap, not speech. Returning early saves
 * a paid call and the second of latency that comes with it.
 */
export const MIN_SECONDS = 0.4;

export class TooShort extends Error {}

/** Read a file as base64 and delete it, whatever happens next. */
async function readAndDiscard(uri: string): Promise<string> {
  const file = new File(uri);
  try {
    return file.base64();
  } finally {
    try {
      file.delete();
    } catch {
      // A cache file that outlives us is reclaimed by the OS. Failing
      // the transcription because cleanup failed would be the wrong
      // trade.
    }
  }
}

/**
 * Send a recording up and get words back.
 *
 * Throws {@link TooShort} for a mistap, so the caller can say nothing
 * rather than show an error for a button somebody brushed.
 */
export async function transcribe(uri: string, seconds: number): Promise<string> {
  if (seconds < MIN_SECONDS) {
    // Still tidy up: a 200ms recording is a file either way.
    await readAndDiscard(uri).catch(() => '');
    throw new TooShort();
  }

  const audio = await readAndDiscard(uri);
  const { data, error } = await api.POST('/v1/speech/transcribe', {
    body: {
      audio_base64: audio,
      content_type: 'audio/wav',
      duration_seconds: Math.min(seconds, MAX_SECONDS),
    } as never,
  });
  if (error || !data) {
    throw new Error('Could not turn that into words. Try again, or type it.');
  }
  return data.text ?? '';
}
