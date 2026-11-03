// Reanimated and Gesture Handler need explicit test setup on SDK 58.
require('react-native-gesture-handler/jestSetup');

// `tapFeedback` reaches for expo-haptics with a dynamic `import()`, which
// jest cannot execute without ESM support - a press in any test rejects
// with "A dynamic import callback was invoked without
// --experimental-vm-modules" before the handler under test ever runs.
// Mocked here rather than per file: every screen gives feedback on tap,
// so every interaction test needs it.
jest.mock('expo-haptics', () => ({
  selectionAsync: jest.fn(async () => {}),
  notificationAsync: jest.fn(async () => {}),
  impactAsync: jest.fn(async () => {}),
  NotificationFeedbackType: { Success: 'success', Warning: 'warning', Error: 'error' },
  ImpactFeedbackStyle: { Light: 'light', Medium: 'medium', Heavy: 'heavy' },
}));
