This is an Expo/React Native mobile application. Prioritize mobile-first patterns, performance, and cross-platform compatibility.

## Expo has changed — do not trust your training data

Expo ships breaking changes every SDK release. APIs you remember are likely renamed, moved, or removed. Before writing any code that touches an Expo, EAS, or React Native API:

1. Read the major version of the `expo` package in `package.json`.
2. Fetch the matching versioned docs: `https://docs.expo.dev/versions/v<major>.0.0/`
3. For anything else, fetch https://docs.expo.dev/llms.txt — an index of all Expo docs with corrections to common LLM misconceptions. Follow its links to the specific page you need; never answer from memory.

## Commands

Use `bunx` instead of `npx` if the project uses bun (`bun.lock` present).

```bash
npx expo install <package>  # ALWAYS use instead of npm/yarn/pnpm/bun add — resolves SDK-compatible versions
npx expo start              # start the dev server
npx expo lint               # lint
npx tsc --noEmit            # typecheck
npx expo-doctor             # diagnose dependency and config issues
npx expo install --fix      # fix incompatible package versions
```

Run lint and typecheck before declaring any task done.

## Navigation & Routing

- Use **Expo Router** for all navigation. Routes live in `src/app/` — every file there is a screen, `_layout.tsx` files define navigators. Keep non-route code (components, hooks, utils) outside `src/app/`.
- Import `Link`, `router`, and `useLocalSearchParams` from `expo-router`.
- Docs: https://docs.expo.dev/router/introduction.md

## Building with EAS

Use EAS to build, sign, and submit the app in the cloud (`eas build`, `eas submit`) and to ship over-the-air updates (`eas update`) — no local Xcode or Android Studio required. Run EAS CLI as `bunx eas-cli <command>` in Bun projects, or `npx eas-cli@latest <command>` otherwise; substitute that for bare `eas` in docs examples.
Docs: https://docs.expo.dev/eas/index.md

## Rules

- If `ios/` and `android/` directories do not exist, they are generated (Continuous Native Generation). Never create or edit them by hand — configure native behavior in `app.json` and config plugins.
- Expo Go only includes its bundled native modules. After adding a library with native code, the app needs a development build: `npx expo run:ios|android` locally, or `eas build --profile development`.
- Prefer recommended Expo modules over third-party libraries, and check your available skills before adding dependencies. Docs: https://docs.expo.dev/versions/latest/index.md

## Testing

Component tests render for real (`@testing-library/react-native` + `jest-expo`).
Four traps, each of which has cost an afternoon:

- **`renderWithProviders` wraps, so `rerender` is safe.** It passes the
  providers as RNTL's `wrapper` rather than as a parent element, which is
  what makes `view.rerender(<Thing />)` keep them. It did not always: when
  it wrapped the element, a rerender replaced the whole tree with a bare
  component and the next hook needing a query client threw "No QueryClient
  set" - in a test that had nothing to do with queries.
- **Never call `unmount()` inside a test.** In RNTL 14 an explicit unmount makes
  every *later* test in the file render an empty tree, so assertions fail with a
  received value of `null` and nothing explains why. When two renders need
  comparing, do both in one test and read each returned instance's `toJSON()`.
- **`render` is async, so `jest.useFakeTimers()` deadlocks it.** Faking timers
  stops the promise `render` returns from ever resolving. Drive a timeout by
  spying on `setTimeout` and invoking the callback it registered, or use real
  timers with a short delay.
- **Wrap anything that queries or reads an inset** in `renderWithProviders`
  (`src/test-support/render.tsx`). Outside a `SafeAreaProvider`, insets report
  zero and every "does this clear the status bar" assertion passes vacuously.

Dynamic `import()` does not run under jest: `jest-expo` transforms with Metro's
caller, which claims dynamic-import support, so babel leaves the call intact and
it throws `A dynamic import callback was invoked without
--experimental-vm-modules`. Import at the top of the file instead - that is why
`tapFeedback` imports `expo-haptics` statically.
