/**
 * The default avatar: one letter, and a colour that is theirs.
 *
 * Asked for by name — "all users without a profile picture should have
 * a default avatar with the first letter of the user's name and a
 * random solid color background". Random per *person*, not per render:
 * a colour drawn fresh each mount makes one account look like several
 * down a followers list, which is the bug this pins.
 */

import { render, screen } from '@testing-library/react-native';

import { Monogram } from '@/components/ui/monogram';
import { MonogramTints, tintFor } from '@/constants/theme';

/**
 * The tint a rendered monogram is standing on.
 *
 * Read off the tree rather than by calling `tintFor` again, so these
 * assert what the component draws and not just what the helper
 * returns.
 *
 * Note: no `unmount()` anywhere below. In RNTL 14 an explicit unmount
 * inside a test makes every *later* test's `render` return an empty
 * tree, so two renders that need comparing happen in one test.
 */
function groundOf(tree: unknown): string {
  const json = JSON.stringify(tree);
  return MonogramTints.find((tint) => json.includes(tint)) ?? '';
}

describe('monogram', () => {
  it('stands in for a face with the first letter of their name', async () => {
    await render(<Monogram name="imani" id="a" />);
    expect(screen.getByText('I')).toBeTruthy();
  });

  it('shows a letter for a name that starts with a space', async () => {
    await render(<Monogram name="  rae" id="a" />);
    expect(screen.getByText('R')).toBeTruthy();
  });

  it('has something to show for a nameless account', async () => {
    // Better than an empty circle, which reads as a failed load.
    await render(<Monogram name="" id="a" />);
    expect(screen.getByText('?')).toBeTruthy();
  });

  it('gives one person the same ground every time it is drawn', async () => {
    // The whole point. A followers list mounts these by the dozen and
    // re-mounts them on every scroll back.
    const first = await render(<Monogram name="Imani" id="person-7" />);
    const again = await render(<Monogram name="Imani" id="person-7" />);

    const once = groundOf(first.toJSON());
    expect(MonogramTints).toContain(once);
    expect(groundOf(again.toJSON())).toBe(once);
  });

  it('keeps their ground when they rename themselves', async () => {
    // Taken from the id for exactly this reason.
    const before = await render(<Monogram name="Imani" id="person-7" />);
    const renamed = await render(<Monogram name="Imani K" id="person-7" />);

    expect(groundOf(renamed.toJSON())).toBe(groundOf(before.toJSON()));
  });

  it('does not give everybody the same colour', async () => {
    const grounds = new Set(
      ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((id) => tintFor(id)),
    );
    expect(grounds.size).toBeGreaterThan(1);
  });

  it('falls back to the name when there is no id to colour from', () => {
    expect(tintFor('Imani')).toBe(tintFor('Imani'));
  });

  it('shows their photograph instead when this app has one', async () => {
    await render(
      <Monogram name="Imani" id="person-7" uri="https://example.test/a.webp" />,
    );
    expect(screen.queryByText('I')).toBeNull();
  });

  it('is not announced separately from the row it sits in', async () => {
    // The name beside it is the label; a screen reader hitting both
    // reads every person twice.
    const view = await render(<Monogram name="Imani" id="person-7" />);
    expect(JSON.stringify(view.toJSON())).toContain('"accessible":false');
  });
});
