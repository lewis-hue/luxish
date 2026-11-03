/**
 * Whether the server knows where to send.
 *
 * **The bug this covers delivered nothing while looking fine.** Every
 * notification was queued correctly, batched correctly, scheduled
 * correctly - and then dropped at the gateway with "No device
 * registered for this account", because the only two callers of
 * `announceDevice` were both inside the notification settings screen.
 * Granting permission once and never going back there meant no device
 * row existed. Nothing errored; the phone was simply quiet.
 */
import { render, waitFor } from '@testing-library/react-native';
import { AppState } from 'react-native';

import { DeviceRegistration } from '@/features/notifications/sync';

/**
 * The foreground listeners this file's renders registered.
 *
 * Stubbed for the whole file rather than spied on inside the one test
 * that needs it: a `mockRestore` part-way through left
 * `AppState.addEventListener` returning undefined, and the *next*
 * test failed in the component's cleanup with an error about
 * `remove` that had nothing to do with what it was checking.
 */
const foreground: ((state: string) => void)[] = [];

// `sync.tsx` sets the foreground handler at module scope, and the real
// one reaches into native on import.
jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  useLastNotificationResponse: () => null,
  addNotificationResponseReceivedListener: () => ({
    remove: () => undefined,
  }),
}));

const mockAnnounce = jest.fn(async () => true);
const mockPermission = jest.fn(async () => 'granted' as string);
const mockRequest = jest.fn(async () => 'granted' as string);
const mockChannel = jest.fn(async () => undefined);
let mockSignedIn = true;

jest.mock('@/api/queries/devices', () => ({
  announceDevice: () => mockAnnounce(),
  forgetDevice: jest.fn(),
}));

jest.mock('@/features/notifications/permission', () => ({
  permissionState: () => mockPermission(),
  requestPermission: () => mockRequest(),
  ensureChannel: () => mockChannel(),
  pushToken: jest.fn(async () => 'ExponentPushToken[x]'),
  deviceTimezone: () => 'Europe/London',
}));

jest.mock('@/features/auth/session', () => ({
  useAuth: () => ({ status: mockSignedIn ? 'signedIn' : 'signedOut' }),
}));

// `sync.tsx` also exports the planner reminders, which reach for a
// query client and a scheduler neither of which this is about.
jest.mock('@/api/queries/notification-prefs', () => ({
  useNotificationPrefs: () => ({ data: undefined }),
}));
jest.mock('@/api/queries/planner', () => ({
  usePlanner: () => ({ data: undefined }),
  addDays: (d: Date) => d,
  isoDay: () => '2026-11-02',
}));

beforeEach(() => {
  foreground.length = 0;
  jest
    .spyOn(AppState, 'addEventListener')
    .mockImplementation(((_: string, handler: (s: string) => void) => {
      foreground.push(handler);
      return { remove: () => undefined };
    }) as never);
  mockAnnounce.mockClear();
  mockPermission.mockClear();
  mockRequest.mockClear();
  mockChannel.mockClear();
  mockPermission.mockResolvedValue('granted');
  mockSignedIn = true;
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('DeviceRegistration', () => {
  it('registers the phone on launch when permission is already given', async () => {
    render(<DeviceRegistration />);
    await waitFor(() => expect(mockAnnounce).toHaveBeenCalled());
  });

  it('never asks for permission itself', async () => {
    // Asking belongs to the settings screen, which explains why first.
    // A system prompt nobody expected at launch is how somebody
    // decides to say no.
    mockPermission.mockResolvedValue('undetermined');
    render(<DeviceRegistration />);
    await waitFor(() => expect(mockPermission).toHaveBeenCalled());
    expect(mockRequest).not.toHaveBeenCalled();
    expect(mockAnnounce).not.toHaveBeenCalled();
  });

  it('sends nothing when permission was refused', async () => {
    mockPermission.mockResolvedValue('denied');
    render(<DeviceRegistration />);
    await waitFor(() => expect(mockPermission).toHaveBeenCalled());
    expect(mockAnnounce).not.toHaveBeenCalled();
  });

  it('does nothing at all while signed out', async () => {
    // A token registered against no account is a notification sent to
    // whoever holds the phone next.
    mockSignedIn = false;
    render(<DeviceRegistration />);
    await waitFor(() => expect(mockPermission).not.toHaveBeenCalled());
    expect(mockAnnounce).not.toHaveBeenCalled();
  });

  it('registers again when the app comes back to the foreground', async () => {
    // Permission is usually granted in the system settings app, which
    // means it happens while this one is backgrounded and this
    // component never re-renders. A token can also be reissued after
    // a restore.
    render(<DeviceRegistration />);
    await waitFor(() => expect(mockAnnounce).toHaveBeenCalledTimes(1));

    foreground.forEach((handler) => handler('active'));
    await waitFor(() => expect(mockAnnounce).toHaveBeenCalledTimes(2));

    // Backgrounding is not a reason to re-register.
    foreground.forEach((handler) => handler('background'));
    await waitFor(() => expect(mockAnnounce).toHaveBeenCalledTimes(2));
  });

  it('makes the Android channel exist before anything can arrive on it', async () => {
    render(<DeviceRegistration />);
    await waitFor(() => expect(mockChannel).toHaveBeenCalled());
  });
});
