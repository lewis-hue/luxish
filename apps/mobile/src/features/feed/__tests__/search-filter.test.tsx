/**
 * The "Filter by" screen the filter icon leads to.
 *
 * The screenshot pins its shape: three radios, a divider, one
 * checkbox, and Reset beside Apply at the bottom. What is worth
 * testing is the behaviour that shape implies - radios are exclusive,
 * the checkbox is not a radio, and nothing reaches the search until
 * Apply.
 */

import { screen, userEvent } from '@testing-library/react-native';

import {
  NO_FILTER,
  type SearchFilter,
  SearchFilterSheet,
  filtered,
} from '@/features/feed/search-filter';
import { renderWithProviders } from '@/test-support/render';

function sheet(filter: SearchFilter, onApply = jest.fn(), onClose = jest.fn()) {
  return {
    onApply,
    onClose,
    ui: (
      <SearchFilterSheet
        visible
        filter={filter}
        onClose={onClose}
        onApply={onApply}
      />
    ),
  };
}

describe('the filter screen', () => {
  it('is titled Filter by', async () => {
    const { ui } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    expect(screen.getByText('Filter by')).toBeTruthy();
  });

  it('offers one kind of thing to search through at a time', async () => {
    const { ui } = sheet(NO_FILTER);
    await renderWithProviders(ui);

    const radios = ['All fits', 'Boards', 'People'].map((label) =>
      screen.getByLabelText(label),
    );
    for (const radio of radios) {
      expect(radio.props.accessibilityRole).toBe('radio');
    }
    const checked = radios.filter((r) => r.props.accessibilityState?.checked);
    expect(checked).toHaveLength(1);
  });

  it('makes the photographs switch a checkbox, not a fourth radio', async () => {
    // It is true or false about any of the three above, so it cannot
    // be in the group with them.
    const { ui } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    const box = screen.getByLabelText('Photographs only');
    expect(box.props.accessibilityRole).toBe('checkbox');
    expect(box.props.accessibilityState?.checked).toBe(false);
  });

  it('says what "photographs only" leaves out', async () => {
    const { ui } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    expect(screen.getByLabelText('Photographs only').props.accessibilityHint).toBe(
      'Leaves out fits drawn by the studio or worn by an avatar.',
    );
  });

  it('holds a change until Apply', async () => {
    // Acting on each tap would re-run the search three times on the way
    // to the combination somebody wanted.
    const { ui, onApply } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    const user = userEvent.setup();

    await user.press(screen.getByLabelText('People'));
    expect(onApply).not.toHaveBeenCalled();

    await user.press(screen.getByLabelText('Apply these filters'));
    expect(onApply).toHaveBeenCalledWith({ kind: 'people', photographsOnly: false });
  });

  it('keeps one radio checked when another is picked', async () => {
    const { ui } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    const user = userEvent.setup();

    await user.press(screen.getByLabelText('Boards'));
    expect(screen.getByLabelText('Boards').props.accessibilityState.checked).toBe(
      true,
    );
    expect(screen.getByLabelText('All fits').props.accessibilityState.checked).toBe(
      false,
    );
  });

  it('carries both choices through one Apply', async () => {
    const { ui, onApply } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    const user = userEvent.setup();

    await user.press(screen.getByLabelText('Boards'));
    await user.press(screen.getByLabelText('Photographs only'));
    await user.press(screen.getByLabelText('Apply these filters'));

    expect(onApply).toHaveBeenCalledWith({ kind: 'boards', photographsOnly: true });
  });

  it('puts everything back with one Reset, without applying it', async () => {
    // Undoing a narrowing is the other half of making one; hunting for
    // the original state tap by tap is how people close the app.
    const { ui, onApply } = sheet({ kind: 'people', photographsOnly: true });
    await renderWithProviders(ui);
    const user = userEvent.setup();

    await user.press(screen.getByLabelText('Reset the filters'));
    expect(screen.getByLabelText('All fits').props.accessibilityState.checked).toBe(
      true,
    );
    expect(
      screen.getByLabelText('Photographs only').props.accessibilityState.checked,
    ).toBe(false);
    expect(onApply).not.toHaveBeenCalled();
  });

  it('opens on what is actually in force', async () => {
    const { ui } = sheet({ kind: 'people', photographsOnly: true });
    await renderWithProviders(ui);
    expect(screen.getByLabelText('People').props.accessibilityState.checked).toBe(
      true,
    );
    expect(
      screen.getByLabelText('Photographs only').props.accessibilityState.checked,
    ).toBe(true);
  });

  it('offers Reset and Apply by those names', async () => {
    const { ui } = sheet(NO_FILTER);
    await renderWithProviders(ui);
    expect(screen.getByText('Reset')).toBeTruthy();
    expect(screen.getByText('Apply')).toBeTruthy();
  });
});

describe('whether the icon should read as filtered', () => {
  it('is not filtered by default', () => {
    expect(filtered(NO_FILTER)).toBe(false);
  });

  it('is filtered once a kind is narrowed', () => {
    expect(filtered({ kind: 'people', photographsOnly: false })).toBe(true);
  });

  it('is filtered on photographs alone', () => {
    expect(filtered({ kind: 'fits', photographsOnly: true })).toBe(true);
  });
});
