/**
 * Holding to talk, and the release that used to be dropped.
 *
 * **The microphone was inert across the whole app and showed nothing.**
 * No dialog, no log, a button that simply stopped responding.
 *
 * `recording` was React state and both halves of the gesture read it.
 * `onPressIn` awaits the permission prompt before setting it;
 * `onPressOut` runs the `stop` closure from whichever render was
 * current when the handler was attached. Let go during that await -
 * which is every first use, because the system dialog is up - and
 * `stop` saw `recording === false`, returned, and stopped nothing.
 * `start` then finished, set the flag, and opened the microphone with
 * nobody left to close it. Every later press read that same flag and
 * returned.
 *
 * One tap, and the feature was gone until the app restarted.
 *
 * The gesture is coordinated by refs now: a ref is written
 * synchronously and read without a closure, so press-in and press-out
 * cannot disagree about whether a gesture is happening.
 *
 * **No manual `act` here.** `render`, `fireEvent` and `waitFor` each
 * wrap their own, and adding another nests them - React logs
 * "overlapping act() calls" and then every later render in this file
 * comes back empty, which reads as a broken component rather than an
 * impatient test. That cost an hour.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { MicButton } from '@/features/stylist/mic-button';

/** Resolves when we say so, so a release can land mid-open. */
function deferred<T>() {
  let settle!: (value: T) => void;
  const promise = new Promise<T>((resolve) => {
    settle = resolve;
  });
  return { promise, settle };
}

const mockStreamCalls: string[] = [];

/** The permission answer, installed per test. */
const mockAskPermission = jest.fn<Promise<{ granted: boolean }>, []>();

const mockFileRecording = {
  uri: 'file:///cache/voice.wav',
  duration: 2.5,
  size: 1024,
  sampleRate: 16_000,
  channels: 1,
  encoding: 'int16' as const,
};

jest.mock('expo-audio', () => ({
  requestRecordingPermissionsAsync: () => mockAskPermission(),
  useAudioStream: () => ({
    isStreaming: false,
    stream: {
      start: async () => {
        mockStreamCalls.push('start');
      },
      stop: () => {
        mockStreamCalls.push('stop');
      },
      startFileRecordingAsync: async () => {
        mockStreamCalls.push('startFile');
      },
      stopFileRecordingAsync: async () => {
        mockStreamCalls.push('stopFile');
        return mockFileRecording;
      },
    },
  }),
  setAudioModeAsync: async () => {},
}));

const mockTranscribe = jest.fn(async () => 'a navy blazer with cream trousers');
jest.mock('@/features/stylist/voice', () => ({
  ...jest.requireActual('@/features/stylist/voice'),
  transcribe: (...args: unknown[]) => mockTranscribe(...(args as [])),
}));

jest.mock('expo-symbols', () => ({ SymbolView: 'SymbolView' }));

const LABEL = 'Hold to talk to the stylist';

beforeEach(() => {
  mockStreamCalls.length = 0;
  mockAskPermission.mockReset();
  mockTranscribe.mockClear();
});

/** Allow the microphone, immediately. */
function allow() {
  mockAskPermission.mockResolvedValue({ granted: true });
}

/**
 * Wait until the button is doing nothing at all.
 *
 * **Every test has to end here.** The release path keeps running after
 * the assertion that interested the test - the session hand-back, the
 * upload, the final `setWorking(false)` - and work still in flight when
 * a test ends overlaps the next test's `render`. React reports
 * "overlapping act() calls" and every later render in the file comes
 * back empty, so one impatient test fails all the others after it.
 */
async function settled() {
  await waitFor(() =>
    expect(screen.getByLabelText(LABEL).props.accessibilityState?.busy).toBe(false),
  );
}

test('a release during the permission prompt neither strands the microphone nor wedges the button', async () => {
  // **The reported bug, start to finish, in one gesture and then a
  // second.** The release lands before the permission answer, which is
  // what happens on every first use because the system dialog is up.
  //
  // Both halves are asserted here rather than in two tests, and that
  // is a concession to the harness: this component keeps working after
  // its assertions - the session hand-back, the upload, the final
  // state write - and any of it still in flight when a test ends
  // overlaps the next test's `render`. React then reports
  // "overlapping act() calls" and every later render in the file comes
  // back empty. One interactive test per file is what runs reliably,
  // so the two assertions that matter share one.
  const prompt = deferred<{ granted: boolean }>();
  mockAskPermission.mockReturnValue(prompt.promise);

  const onText = jest.fn();
  await render(<MicButton onText={onText} compact />);
  const button = screen.getByLabelText(LABEL);

  fireEvent(button, 'pressIn');
  fireEvent(button, 'pressOut'); // let go before the prompt is answered
  prompt.settle({ granted: true });

  // Whatever the open managed to do, the release has to have closed
  // it. Before the fix, `stop` read stale state, returned, and left
  // the microphone running with nothing able to close it.
  await waitFor(() => expect(mockStreamCalls).toContain('stop'));
  const opened = mockStreamCalls.lastIndexOf('startFile');
  const closed = mockStreamCalls.lastIndexOf('stopFile');
  expect(opened === -1 || closed > opened).toBe(true);

  // **And the part that actually broke the feature.** The dropped
  // release was recoverable; the flag it left behind was not. Every
  // press after it read that flag and returned, silently, for ever.
  mockStreamCalls.length = 0;
  allow();
  fireEvent(button, 'pressIn');
  await waitFor(() => expect(mockStreamCalls).toContain('startFile'));

  // A full gesture still produces words.
  fireEvent(button, 'pressOut');
  await waitFor(() => expect(onText).toHaveBeenCalled());
  expect(mockTranscribe).toHaveBeenCalledWith('file:///cache/voice.wav', 2.5);
  expect(onText).toHaveBeenCalledWith('a navy blazer with cream trousers');
});
