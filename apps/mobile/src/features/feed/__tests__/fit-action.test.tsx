/**
 * The three things you do to a fit, drawn as one set.
 *
 * Taken from the reference: a heart carrying its tally, a bubble
 * carrying its own, a bare share glyph, evenly spaced and at one
 * stroke. They used to live in two files with their own sizes and
 * gaps, which is how a row of controls stops reading as a row.
 */

import { screen, userEvent } from '@testing-library/react-native';

import { ACTION_WIDTH, ActionIcon, COUNT_SLOT, FitAction } from '@/features/feed/fit-action';
import { renderWithProviders } from '@/test-support/render';

const HEART = { ios: 'heart', android: 'favorite_border', web: 'favorite' } as const;

function tree(): string {
  return JSON.stringify(screen.toJSON());
}

describe('how an action is drawn', () => {
  it('sets the stroke rather than leaving it to the system', async () => {
    // Set explicitly so the three glyphs match each other. `light` was
    // tried and was a half-step too thin beside the reference - the
    // share tray in particular lost its shape.
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={302} onPress={() => {}} />,
    );
    expect(tree()).toContain(`"weight":"${ActionIcon.weight}"`);
    expect(ActionIcon.weight).toBe('regular');
  });

  it('draws every action at one size', () => {
    // Asserted on the token rather than per call site: three glyphs at
    // three sizes is what the single component exists to prevent.
    expect(ActionIcon.size).toBe(26);
    expect(ActionIcon.weight).toBe('regular');
  });

  it('shows the tally beside the glyph', async () => {
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={302} onPress={() => {}} />,
    );
    expect(screen.getByText('302')).toBeTruthy();
  });

  it('shortens a long tally rather than widening the row', async () => {
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={1632} onPress={() => {}} />,
    );
    expect(screen.getByText('1.6K')).toBeTruthy();
  });

  it('shows no tally at zero', async () => {
    // A nought under somebody's photograph reads as a verdict on it, and
    // the reference shows a bare glyph until there is something to count.
    await renderWithProviders(
      <FitAction label="Add a comment" icon={HEART} count={0} onPress={() => {}} />,
    );
    expect(screen.queryByText('0')).toBeNull();
  });

  it('shows no tally where there is nothing to count', async () => {
    // Sharing has no number in the reference at all.
    await renderWithProviders(
      <FitAction label="Share this fit" icon={HEART} onPress={() => {}} />,
    );
    expect(tree()).not.toMatch(/"children":\["\d/);
  });

  it('shows their own reaction in place of the glyph', async () => {
    await renderWithProviders(
      <FitAction label="Reacted" icon={HEART} emoji="🔥" count={5} onPress={() => {}} />,
    );
    expect(screen.getByText('🔥')).toBeTruthy();
  });
});

describe('what an action announces', () => {
  it('names itself and its tally', async () => {
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={302} onPress={() => {}} />,
    );
    expect(screen.getByLabelText('React. 302 so far.')).toBeTruthy();
  });

  it('names itself alone when there is no tally', async () => {
    // "Share this fit. 0 so far." is a sentence about nothing.
    await renderWithProviders(
      <FitAction label="Share this fit" icon={HEART} onPress={() => {}} />,
    );
    expect(screen.getByLabelText('Share this fit')).toBeTruthy();
  });

  it('says a hold does something, where it does', async () => {
    await renderWithProviders(
      <FitAction
        label="React"
        hint="Hold to pick a different reaction"
        icon={HEART}
        count={1}
        onPress={() => {}}
        onLongPress={() => {}}
      />,
    );
    expect(screen.getByLabelText('React. 1 so far.').props.accessibilityHint).toBe(
      'Hold to pick a different reaction',
    );
  });
});

describe('pressing one', () => {
  it('runs the action', async () => {
    const onPress = jest.fn();
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={1} onPress={onPress} />,
    );
    await userEvent.setup().press(screen.getByLabelText('React. 1 so far.'));
    expect(onPress).toHaveBeenCalled();
  });
});

describe('the row does not move when the counts arrive', () => {
  // The reported bug: for the first moment of every pin there are no
  // counts, and the slot collapsed - so the share glyph sat left of
  // where it was about to end up and jumped right the instant a
  // comment count landed. Two posts side by side had their controls
  // in different places for the same reason.
  it('holds the tally slot open with no count at all', async () => {
    await renderWithProviders(
      <FitAction label="React" icon={HEART} onPress={() => {}} />,
    );
    expect(tree()).toContain(`"minWidth":${COUNT_SLOT}`);
  });

  it('holds it open at zero, which is drawn as nothing', async () => {
    // Zero is still not printed - a nought under somebody's
    // photograph reads as a verdict - but it reserves its room.
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={0} onPress={() => {}} />,
    );
    expect(tree()).toContain(`"minWidth":${COUNT_SLOT}`);
    expect(tree()).not.toContain('>0<');
  });

  it('reserves the same room once there is a count', async () => {
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={4} onPress={() => {}} />,
    );
    expect(tree()).toContain(`"minWidth":${COUNT_SLOT}`);
  });

  it('still reads the tally out', async () => {
    // Reserving the slot must not cost a screen reader the count.
    // An earlier version hid the slot from the accessibility tree to
    // keep a blank from being announced, which took the number with
    // it.
    await renderWithProviders(
      <FitAction label="React" icon={HEART} count={4} onPress={() => {}} />,
    );
    expect(tree()).toContain('React. 4 so far.');
  });

  it('is wide enough for the widest tally this app can print', () => {
    // `compactCount` never returns more than four characters: `999`
    // is the longest plain number and `1.2K` the longest short
    // form. Sized for that, the row cannot move at any count - a
    // two-character slot still nudged everything along at three
    // digits, which is what prompted this.
    const widest = ['999', '1.2K', '12K', '1.2M'];
    for (const value of widest) expect(value.length).toBeLessThanOrEqual(4);
    expect(COUNT_SLOT).toBeGreaterThanOrEqual(24);
  });

  it('holds the same room at one digit and at four', async () => {
    // The whole point. Liking something takes a count from 4 to 5,
    // or from 999 to 1.0K, and the share glyph beside it must not
    // move either time.
    for (const count of [0, 4, 99, 999, 1200]) {
      const view = await renderWithProviders(
        <FitAction label="React" icon={HEART} count={count} onPress={() => {}} />,
      );
      expect(JSON.stringify(view.toJSON())).toContain(
        `"minWidth":${COUNT_SLOT}`,
      );
    }
  });

  it('tells the skeleton the width to draw', () => {
    // The loading row is drawn from this, so it cannot drift from
    // what replaces it.
    expect(ACTION_WIDTH).toBe(ActionIcon.size + 8 + COUNT_SLOT);
  });
});
