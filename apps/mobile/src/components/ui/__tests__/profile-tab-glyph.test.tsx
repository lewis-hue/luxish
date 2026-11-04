/**
 * The Profile chip shows whoever is signed in.
 *
 * It drew `person.crop.circle.fill` for everybody - the icon for the
 * idea of an account rather than for the account in use - so the bar
 * read as signed out on a signed-in phone. These pin the three states
 * and, more importantly, the order between them: a photograph beats a
 * letter, and a letter beats the symbol, but a letter is never
 * invented for somebody we cannot name.
 */
import { screen } from '@testing-library/react-native';

import { ProfileTabGlyph } from '@/components/ui/profile-tab-glyph';
import { renderWithProviders } from '@/test-support/render';

const mockMe = jest.fn();
const mockPhoto = jest.fn();
const mockAuth = jest.fn();

jest.mock('@/api/queries/me', () => ({
  ...jest.requireActual('@/api/queries/me'),
  useMe: () => mockMe(),
  useProfilePhoto: () => mockPhoto(),
}));
jest.mock('@/features/auth/session', () => ({
  ...jest.requireActual('@/features/auth/session'),
  useAuth: () => mockAuth(),
}));

const glyph = (
  <ProfileTabGlyph focused={false} tint="#111" icon="person.crop.circle.fill" />
);

beforeEach(() => {
  mockAuth.mockReturnValue({ status: 'signedIn' });
  mockMe.mockReturnValue({ data: null });
  mockPhoto.mockReturnValue(null);
});

test('their photograph is the chip', async () => {
  mockMe.mockReturnValue({
    data: { displayName: 'Lewis Muguna', profilePhotoAssetId: 'a1' },
  });
  mockPhoto.mockReturnValue('file:///profile/a1');

  await renderWithProviders(glyph);

  // `expo-image` normalises a single source into a list.
  expect(screen.getByTestId('profile-tab-photo').props.source).toEqual([
    { uri: 'file:///profile/a1' },
  ]);
  // And it is the picture, not the letter, when both are available.
  expect(screen.queryByText('L')).toBeNull();
});

test('with no photograph it is the initial of their first name', async () => {
  mockMe.mockReturnValue({
    data: { displayName: 'Lewis Muguna', profilePhotoAssetId: null },
  });

  await renderWithProviders(glyph);

  // Their first name's letter, not their surname's and not both.
  expect(screen.getByText('L')).toBeTruthy();
});

test('an email stands in when no name was given', async () => {
  mockMe.mockReturnValue({
    data: { email: 'rena.daily@luxish.local', profilePhotoAssetId: null },
  });

  await renderWithProviders(glyph);

  expect(screen.getByText('R')).toBeTruthy();
});

test('a letter is not invented for somebody we cannot name', async () => {
  // `greetingName` refuses an account-shaped local part. A chip
  // reading "U" for `user42@` is a worse answer than the icon,
  // because it looks like somebody's initial and belongs to nobody.
  mockMe.mockReturnValue({
    data: { email: 'user42@luxish.local', profilePhotoAssetId: null },
  });

  await renderWithProviders(glyph);

  expect(screen.queryByText('U')).toBeNull();
  expect(screen.getByTestId('profile-tab-symbol')).toBeTruthy();
});

test('signed out it is the symbol', async () => {
  mockAuth.mockReturnValue({ status: 'signedOut' });

  await renderWithProviders(glyph);

  expect(screen.getByTestId('profile-tab-symbol')).toBeTruthy();
});
