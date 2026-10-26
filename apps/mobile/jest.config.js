/** @type {import('jest').Config} */
module.exports = {
  preset: 'jest-expo',
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
