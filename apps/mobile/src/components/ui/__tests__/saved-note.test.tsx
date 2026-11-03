/**
 * What the save notice says, and that it leaves on its own.
 *
 * From the screenshot: "Saved to Profile" with an Organise beside it.
 * Two things are easy to break - the wording, which has to name the
 * destination in the destination's own words, and the going away,
 * which is what stops it being a thing to dismiss.
 */

import { screen } from '@testing-library/react-native';

import { SavedNote } from '@/components/ui/saved-note';
import { Spacing } from '@/constants/theme';
import { INSETS, renderWithProviders } from '@/test-support/render';

describe('the save notice', () => {
  it('says where the picture went', async () => {
    await renderWithProviders(
      <SavedNote visible where="Profile" onOrganise={() => {}} onDone={() => {}} />,
    );
    expect(screen.getByText('Saved to Profile')).toBeTruthy();
  });

  it('names the board when it went to one', async () => {
    await renderWithProviders(
      <SavedNote
        visible
        where="Summer linen"
        onOrganise={() => {}}
        onDone={() => {}}
      />,
    );
    expect(screen.getByText('Saved to Summer linen')).toBeTruthy();
  });

  it('offers Organise rather than asking which board', async () => {
    // The save already happened. A sheet here would make every save a
    // two-step decision.
    await renderWithProviders(
      <SavedNote visible where="Profile" onOrganise={() => {}} onDone={() => {}} />,
    );
    expect(screen.getByText('Organise')).toBeTruthy();
  });

  it('is nothing at all when there is nothing to report', async () => {
    await renderWithProviders(
      <SavedNote
        visible={false}
        where="Profile"
        onOrganise={() => {}}
        onDone={() => {}}
      />,
    );
    expect(screen.queryByText('Saved to Profile')).toBeNull();
  });

  it('clears the status bar', async () => {
    // It sits over the picture at the top of the screen, so the inset
    // is the difference between readable and under the clock.
    await renderWithProviders(
      <SavedNote visible where="Profile" onOrganise={() => {}} onDone={() => {}} />,
    );
    const tree = JSON.stringify(screen.toJSON());
    expect(tree).toContain(`"top":${INSETS.top + Spacing.one}`);
  });

  it('is announced without stealing focus', async () => {
    // Politely: somebody who just pressed Save is still reading the
    // picture, not waiting to be interrupted.
    await renderWithProviders(
      <SavedNote visible where="Profile" onOrganise={() => {}} onDone={() => {}} />,
    );
    expect(JSON.stringify(screen.toJSON())).toContain(
      '"accessibilityLiveRegion":"polite"',
    );
  });

  it('does not push the page down by its own height', async () => {
    // Laid over, not in the layout - otherwise the fit under it jumps
    // twice, once when the notice arrives and once when it leaves.
    await renderWithProviders(
      <SavedNote visible where="Profile" onOrganise={() => {}} onDone={() => {}} />,
    );
    expect(JSON.stringify(screen.toJSON())).toContain('"position":"absolute"');
  });

  it('leaves on its own, after long enough to read and reach', async () => {
    // Driven through the timer it registers rather than by waiting it
    // out: faking jest's timers stops RNTL 14's async `render` from
    // ever resolving, so the component would never mount to be tested.
    const timers = jest.spyOn(global, 'setTimeout');
    const done = jest.fn();
    try {
      await renderWithProviders(
        <SavedNote visible where="Profile" onOrganise={() => {}} onDone={done} />,
      );

      const scheduled = timers.mock.calls.find(
        ([, delay]) => typeof delay === 'number' && delay >= 3000,
      );
      expect(scheduled).toBeDefined();
      // Long enough to read "Saved to Profile" and reach Organise, and
      // short enough that it is gone before it is in the way.
      expect(scheduled![1]).toBeLessThanOrEqual(8000);

      expect(done).not.toHaveBeenCalled();
      (scheduled![0] as () => void)();
      expect(done).toHaveBeenCalled();
    } finally {
      timers.mockRestore();
    }
  });
});
