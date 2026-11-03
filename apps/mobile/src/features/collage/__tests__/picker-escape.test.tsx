/**
 * Somebody must always be able to leave the picker.
 *
 * It accepted an `onClose` prop and never called it. The only ways
 * off the sheet were picking a picture or Android's hardware back,
 * so on iOS a person who opened it and changed their mind was stuck
 * on the screen - and because the sheet is a `Modal`, the canvas's
 * own Close control underneath it was unreachable too.
 *
 * The drag handle is not an escape: it moves the sheet aside, and a
 * sheet moved aside still covers what is under it.
 */

import { screen, userEvent } from '@testing-library/react-native';

// The sheet reads a safe-area inset, and outside a provider that
// throws rather than returning zero (apps/mobile/AGENTS.md).
import { renderWithProviders } from '@/test-support/render';

import { CollagePicker } from '@/features/collage/picker';

// The sheet's drag handle needs gesture-handler's UI runtime, which
// does not exist under jest - without this the suite fails to run at
// all with "`getUIRuntimeHolder` is not supported on web". The
// gesture is not what is under test here; being able to leave is.
jest.mock('react-native-gesture-handler', () => {
  const { View } = jest.requireActual('react-native');
  const noop = () => chainable;
  const chainable: Record<string, unknown> = {};
  for (const name of [
    'onStart', 'onUpdate', 'onEnd', 'enabled', 'minDistance',
    'runOnJS', 'simultaneousWithExternalGesture',
  ]) {
    chainable[name] = noop;
  }
  return {
    Gesture: {
      Pan: () => chainable,
      Tap: () => chainable,
      Pinch: () => chainable,
      Rotation: () => chainable,
      Simultaneous: () => chainable,
      Exclusive: () => chainable,
    },
    GestureDetector: ({ children }: { children: React.ReactNode }) => children,
    GestureHandlerRootView: View,
  };
});

jest.mock('@/api/queries/discover-feed', () => ({
  useSavedFits: () => ({ data: [], isPending: false }),
}));
jest.mock('@/api/queries/moodboards', () => ({
  useMoodboards: () => ({ data: [], isPending: false }),
}));
jest.mock('@/api/queries/post-media', () => ({
  usePostImages: () => ({ data: {}, isPending: false }),
  usePostImage: () => ({ data: null }),
}));
jest.mock('@/api/queries/tags', () => ({
  useTagFeed: () => ({ data: [], isPending: false }),
}));

it('offers a way out', async () => {
  const onClose = jest.fn();
  await renderWithProviders(
    <CollagePicker onPick={jest.fn()} onClose={onClose} />,
  );

  const close = await screen.findByLabelText('Close');
  await userEvent.press(close);

  expect(onClose).toHaveBeenCalled();
});
