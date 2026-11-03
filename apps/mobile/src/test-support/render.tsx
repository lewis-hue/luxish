import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react-native';
import { useState, type ReactElement, type ReactNode } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

/**
 * A component under the providers it is written to run under.
 *
 * Screens here read from React Query and sit inside the safe area, and
 * neither is optional: a component that calls a query hook outside a
 * client throws, and `useSafeAreaInsets` outside a provider reports
 * zero inset, which quietly hides every "does this clear the status
 * bar" assertion.
 *
 * **Retries off, and a fresh client per render.** A query that fails in
 * a test should fail once and immediately - with retries on, the
 * assertion races three backoffs - and a client shared between tests
 * carries one test's cached answer into the next.
 */

/** The frame a phone actually reports, so insets are not all zero. */
const FRAME = { x: 0, y: 0, width: 390, height: 844 };
const INSETS = { top: 47, left: 0, right: 0, bottom: 34 };

/**
 * The providers, as a wrapper.
 *
 * **A wrapper rather than a parent element, so `rerender` survives.**
 * Wrapping the element handed in means a later
 * `view.rerender(<Thing />)` replaces the whole tree - providers and
 * all - with a bare component, and the next hook that needs a client
 * throws "No QueryClient set". RNTL re-applies a `wrapper` on every
 * rerender, which is the behaviour every test here assumed it already
 * had.
 *
 * The client is held in state so it is the same one across rerenders:
 * built inline it would be new on each, and a test that writes to the
 * cache and then rerenders would find it empty.
 */
function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <SafeAreaProvider initialMetrics={{ frame: FRAME, insets: INSETS }}>
        {children}
      </SafeAreaProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(ui: ReactElement) {
  return render(ui, { wrapper: Providers });
}

export { INSETS, FRAME };
