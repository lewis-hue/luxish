import { useSyncExternalStore } from 'react';
import { useColorScheme as useRNColorScheme } from 'react-native';

/** Never emits, so the snapshot is read once per hydration boundary. */
const subscribe = () => () => {};

/**
 * `web.output` is `server` on SDK 58, so the first paint is rendered on the server
 * where no colour scheme exists. We therefore report 'light' for the server snapshot
 * and the real scheme for the client snapshot.
 *
 * Uses `useSyncExternalStore` rather than a `useState` + `useEffect` hydration flag:
 * both avoid a hydration mismatch, but setting state inside an effect triggers a
 * second, cascading render on every mount.
 */
export function useColorScheme() {
  const colorScheme = useRNColorScheme();
  const hydrated = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  return hydrated ? colorScheme : 'light';
}
