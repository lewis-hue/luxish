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
    // Metro resolves a bundled image to an opaque handle; jest has no asset
    // pipeline, so without this any module registering a cover fails to
    // resolve and its whole test file vanishes rather than failing visibly.
    '\.(png|jpg|jpeg|webp|gif|svg|ttf|otf)$': '<rootDir>/__mocks__/asset.js',
  },
  collectCoverageFrom: ['src/**/*.{ts,tsx}', '!src/**/__tests__/**'],
};
