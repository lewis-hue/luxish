/** @type {import('jest').Config} */
module.exports = {
  preset: 'jest-expo',
  // Reanimated 4 ships a resolver that swaps its native-only modules for the
  // web implementations under jest. Without it, importing anything from
  // 'react-native-reanimated' crashes in `react-native-worklets` while trying
  // to install native unpackers, so no component using an animated style can
  // be tested at all.
  resolver: 'react-native-reanimated/jest/resolver',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  // Token and branding tests are pure logic; feature tests render components.
  testMatch: ['<rootDir>/src/**/__tests__/**/*.{test,spec}.{ts,tsx}'],
  // The template's theme imports `global.css` for web font variables; jest cannot
  // parse CSS, and the declarations are irrelevant to native token tests.
  moduleNameMapper: {
    '\.(css)$': '<rootDir>/__mocks__/style.js',
  },
  collectCoverageFrom: ['src/**/*.{ts,tsx}', '!src/**/__tests__/**'],
};
